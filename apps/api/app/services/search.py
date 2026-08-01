"""Cross-domain full-text search service.

Provides unified search across all major entity types in the Sports Intelligence OS
platform, with relevance scoring, snippet highlighting, and pagination.

PostgreSQL is the only supported database.  Search uses ``to_tsvector`` /
``plainto_tsquery`` / ``ts_rank`` for stemming, ranking and GIN-index utilisation.
Because PostgreSQL's built-in ``english`` dictionary does not segment CJK text,
Chinese queries fall back to a literal ``ilike '%query%'`` match (the same
heuristic scoring used for Latin queries when tsvector is unavailable).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import AutomationRule, NotificationChannel
from app.models.editorial_rules import RuleSet
from app.models.generation import GenerationRun, GenerationWorkflow
from app.models.monitoring import Account, ContentItem, Platform
from app.models.news import Article, TopicEvent
from app.models.topics import SavedTopic

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    """A single search result with relevance metadata."""

    entity_type: str = Field(..., description="Entity type key (e.g. 'account', 'article')")
    entity_id: UUID = Field(..., description="Primary key of the matched entity")
    title: str = Field(..., description="Primary display name of the entity")
    subtitle: str = Field(default="", description="Secondary contextual information")
    snippet: str = Field(
        default="",
        description="Matching text excerpt with <mark>-highlighted query terms",
    )
    url: str = Field(default="", description="Frontend route for the entity detail page")
    score: float = Field(
        default=1.0,
        description="Relevance score (higher is better). PostgreSQL uses ts_rank; "
        "fallback uses 3=exact title, 2=partial title, 1=other field.",
    )
    matched_fields: list[str] = Field(
        default_factory=list,
        description="Names of the fields that matched the query",
    )


class SearchPage(BaseModel):
    """Paginated search results."""

    items: list[SearchResult] = Field(default_factory=list)
    total: int = Field(default=0, description="Total number of matching results")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    pages: int = Field(default=0, description="Total number of pages")
    query: str = Field(default="")
    search_backend: str = Field(default="tsvector", description="Active search backend")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

ALL_ENTITY_TYPES: frozenset[str] = frozenset({
    "account",
    "content",
    "article",
    "event",
    "rule",
    "automation_rule",
    "topic",
    "generation_run",
    "notification_channel",
})

_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

_ENTITY_URL_TEMPLATES: dict[str, str] = {
    "account": "/accounts/{id}",
    "content": "/contents/{id}",
    "article": "/news/{id}",
    "event": "/events/{id}",
    "rule": "/rules/{id}",
    "automation_rule": "/automations/{id}",
    "topic": "/topics",
    "generation_run": "/generations/{id}",
    "notification_channel": "/notification-channels",
}


def _highlight(text: str | None, query: str) -> str:
    """Return *text* with every occurrence of *query* wrapped in ``<mark>`` tags."""
    if not text:
        return ""
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    match = pattern.search(text)
    if match is None:
        return text[:160] + ("..." if len(text) > 160 else "")

    start = max(0, match.start() - 60)
    end = min(len(text), match.end() + 100)
    excerpt = text[start:end]
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(text):
        excerpt = excerpt + "..."

    return pattern.sub(lambda m: f"<mark>{m.group()}</mark>", excerpt)


def _score_for(
    query: str,
    title_value: str | None,
    matched_fields: list[str],
) -> float:
    """Compute the simple relevance score (fallback for non-PostgreSQL)."""
    if title_value and query.lower() == title_value.strip().lower():
        return 3.0
    if "title" in matched_fields or "display_name" in matched_fields or "name" in matched_fields:
        return 2.0
    return 1.0


@dataclass
class _RawHit:
    """Intermediate representation before building the public result."""

    entity_type: str
    entity_id: UUID
    title: str
    subtitle: str
    raw_snippet_text: str
    score: float
    matched_fields: list[str]
    sort_timestamp: Any


def _coalesce_text(column: Any) -> Any:
    """Coalesce a nullable column to empty string and cast to text for tsvector."""
    return func.coalesce(cast(column, String), "")


def _ts_match(query: str, *columns: Any) -> Any:
    """Build a PostgreSQL ``to_tsvector(...) @@ plainto_tsquery(...)`` expression.

    Multiple columns are concatenated with ``||' '||`` so that all fields are
    searched in a single tsvector.
    """
    if len(columns) == 1:
        combined = _coalesce_text(columns[0])
    else:
        combined = _coalesce_text(columns[0])
        for col in columns[1:]:
            combined = combined + " " + _coalesce_text(col)
    return func.to_tsvector("english", combined).op("@@")(func.plainto_tsquery("english", query))


def _ts_rank(query: str, *columns: Any) -> Any:
    """Build a PostgreSQL ``ts_rank(...)`` expression for relevance scoring."""
    if len(columns) == 1:
        combined = _coalesce_text(columns[0])
    else:
        combined = _coalesce_text(columns[0])
        for col in columns[1:]:
            combined = combined + " " + _coalesce_text(col)
    return func.ts_rank(
        func.to_tsvector("english", combined),
        func.plainto_tsquery("english", query),
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SearchService:
    """Cross-domain full-text search backed by PostgreSQL tsvector (with an
    ``ilike`` fallback for CJK queries that the English dictionary cannot segment).
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @property
    def backend(self) -> str:
        return "tsvector"

    def _uses_tsvector(self, query: str) -> bool:
        """Use the English dictionary only when it can actually tokenize the query.

        PostgreSQL's built-in ``english`` configuration does not segment CJK text,
        so Chinese queries need the literal ``ilike`` path.
        """
        return _CJK_PATTERN.search(query) is None

    def _backend_for(self, query: str) -> str:
        return "tsvector" if self._uses_tsvector(query) else "ilike"

    # -- public API ---------------------------------------------------------

    async def search(
        self,
        workspace_id: UUID,
        query: str,
        page: int = 1,
        page_size: int = 20,
        entity_types: list[str] | None = None,
    ) -> SearchPage:
        """Search across all (or selected) entity types with pagination."""
        query = query.strip()
        if not query:
            return SearchPage(
                query=query,
                page=page,
                page_size=page_size,
                search_backend=self.backend,
            )

        page = max(1, page)
        page_size = max(1, min(page_size, 100))

        wanted = (
            frozenset(entity_types) & ALL_ENTITY_TYPES
            if entity_types
            else ALL_ENTITY_TYPES
        )

        hits: list[_RawHit] = []

        dispatch: dict[str, Any] = {
            "account": self._search_accounts,
            "content": self._search_content,
            "article": self._search_articles,
            "event": self._search_events,
            "rule": self._search_rules,
            "automation_rule": self._search_automation_rules,
            "topic": self._search_topics,
            "generation_run": self._search_generation_runs,
            "notification_channel": self._search_notification_channels,
        }

        for etype in wanted:
            searcher = dispatch.get(etype)
            if searcher is not None:
                hits.extend(await searcher(workspace_id, query))

        hits.sort(key=lambda h: (h.score, h.sort_timestamp), reverse=True)

        total = len(hits)
        pages = (total + page_size - 1) // page_size
        offset = (page - 1) * page_size
        page_hits = hits[offset : offset + page_size]

        items = [
            SearchResult(
                entity_type=h.entity_type,
                entity_id=h.entity_id,
                title=h.title,
                subtitle=h.subtitle,
                snippet=_highlight(h.raw_snippet_text, query),
                url=_ENTITY_URL_TEMPLATES.get(h.entity_type, "").format(id=h.entity_id),
                score=h.score,
                matched_fields=h.matched_fields,
            )
            for h in page_hits
        ]

        return SearchPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            query=query,
            search_backend=self._backend_for(query),
        )

    # -- private searchers --------------------------------------------------

    async def _search_accounts(self, workspace_id: UUID, query: str) -> list[_RawHit]:
        like = f"%{query}%"
        if self._uses_tsvector(query):
            stmt = (
                select(
                    Account,
                    Platform.name.label("platform_name"),
                    _ts_rank(
                        query, Account.display_name, Account.external_id, Platform.name
                    ).label("rank"),
                )
                .join(Platform, Account.platform_id == Platform.id)
                .where(Account.workspace_id == workspace_id)
                .where(_ts_match(query, Account.display_name, Account.external_id, Platform.name))
                .order_by(text("rank DESC"))
                .limit(200)
            )
        else:
            stmt = (
                select(Account, Platform.name.label("platform_name"), text("0 as rank"))
                .join(Platform, Account.platform_id == Platform.id)
                .where(Account.workspace_id == workspace_id)
                .where(
                    or_(
                        Account.display_name.ilike(like),
                        Account.external_id.ilike(like),
                        Platform.name.ilike(like),
                    )
                )
                .order_by(Account.updated_at.desc())
                .limit(200)
            )
        result = await self._db.execute(stmt)
        hits: list[_RawHit] = []
        for row in result.all():
            account: Account = row[0]
            platform_name: str = row[1]
            rank: float = float(row[2]) if len(row) > 2 else 0.0
            matched: list[str] = []
            if query.lower() in (account.display_name or "").lower():
                matched.append("display_name")
            if query.lower() in (account.external_id or "").lower():
                matched.append("external_id")
            if query.lower() in (platform_name or "").lower():
                matched.append("platform_name")

            snippet_text = " / ".join(
                filter(None, [account.display_name, account.external_id, platform_name])
            )
            score = (
                rank
                if self._uses_tsvector(query) and rank > 0
                else _score_for(query, account.display_name, matched)
            )
            hits.append(
                _RawHit(
                    entity_type="account",
                    entity_id=account.id,
                    title=account.display_name,
                    subtitle=f"@{account.username or account.external_id} · {platform_name}",
                    raw_snippet_text=snippet_text,
                    score=score,
                    matched_fields=matched,
                    sort_timestamp=account.updated_at,
                )
            )
        return hits

    async def _search_content(self, workspace_id: UUID, query: str) -> list[_RawHit]:
        like = f"%{query}%"
        if self._uses_tsvector(query):
            stmt = (
                select(
                    ContentItem,
                    _ts_rank(
                        query,
                        ContentItem.title,
                        ContentItem.description,
                        ContentItem.external_id,
                    ).label("rank"),
                )
                .where(ContentItem.workspace_id == workspace_id)
                .where(
                    _ts_match(
                        query,
                        ContentItem.title,
                        ContentItem.description,
                        ContentItem.external_id,
                    )
                )
                .order_by(text("rank DESC"))
                .limit(200)
            )
        else:
            stmt = (
                select(ContentItem, text("0 as rank"))
                .where(ContentItem.workspace_id == workspace_id)
                .where(
                    or_(
                        ContentItem.title.ilike(like),
                        ContentItem.description.ilike(like),
                        ContentItem.external_id.ilike(like),
                    )
                )
                .order_by(ContentItem.updated_at.desc())
                .limit(200)
            )
        result = await self._db.execute(stmt)
        hits: list[_RawHit] = []
        for row in result.all():
            item: ContentItem = row[0]
            rank: float = float(row[1]) if len(row) > 1 else 0.0
            matched: list[str] = []
            if query.lower() in (item.title or "").lower():
                matched.append("title")
            if query.lower() in (item.description or "").lower():
                matched.append("description")
            if query.lower() in (item.external_id or "").lower():
                matched.append("external_id")

            snippet_text = " / ".join(
                filter(None, [item.title, item.description, item.external_id])
            )
            score = (
                rank
                if self._uses_tsvector(query) and rank > 0
                else _score_for(query, item.title, matched)
            )
            hits.append(
                _RawHit(
                    entity_type="content",
                    entity_id=item.id,
                    title=item.title,
                    subtitle=f"{item.content_type} · {item.status}",
                    raw_snippet_text=snippet_text,
                    score=score,
                    matched_fields=matched,
                    sort_timestamp=item.updated_at,
                )
            )
        return hits

    async def _search_articles(self, workspace_id: UUID, query: str) -> list[_RawHit]:
        like = f"%{query}%"
        if self._uses_tsvector(query):
            stmt = (
                select(
                    Article,
                    _ts_rank(query, Article.title, Article.summary).label("rank"),
                )
                .where(Article.workspace_id == workspace_id)
                .where(_ts_match(query, Article.title, Article.summary, Article.canonical_url))
                .order_by(text("rank DESC"))
                .limit(200)
            )
        else:
            stmt = (
                select(Article, text("0 as rank"))
                .where(Article.workspace_id == workspace_id)
                .where(
                    or_(
                        Article.title.ilike(like),
                        Article.summary.ilike(like),
                        Article.canonical_url.ilike(like),
                    )
                )
                .order_by(Article.updated_at.desc())
                .limit(200)
            )
        result = await self._db.execute(stmt)
        hits: list[_RawHit] = []
        for row in result.all():
            article: Article = row[0]
            rank: float = float(row[1]) if len(row) > 1 else 0.0
            matched: list[str] = []
            if query.lower() in (article.title or "").lower():
                matched.append("title")
            if query.lower() in (article.summary or "").lower():
                matched.append("summary")
            if query.lower() in (article.canonical_url or "").lower():
                matched.append("canonical_url")

            snippet_text = " / ".join(
                filter(None, [article.title, article.summary, article.canonical_url])
            )
            score = (
                rank
                if self._uses_tsvector(query) and rank > 0
                else _score_for(query, article.title, matched)
            )
            hits.append(
                _RawHit(
                    entity_type="article",
                    entity_id=article.id,
                    title=article.title,
                    subtitle=f"{article.sport or ''} · {article.league or ''}".strip(" ·"),
                    raw_snippet_text=snippet_text,
                    score=score,
                    matched_fields=matched,
                    sort_timestamp=article.updated_at,
                )
            )
        return hits

    async def _search_events(self, workspace_id: UUID, query: str) -> list[_RawHit]:
        like = f"%{query}%"
        if self._uses_tsvector(query):
            stmt = (
                select(
                    TopicEvent,
                    _ts_rank(
                        query, TopicEvent.title, TopicEvent.sport,
                        TopicEvent.league, TopicEvent.summary,
                    ).label("rank"),
                )
                .where(TopicEvent.workspace_id == workspace_id)
                .where(
                    _ts_match(
                        query, TopicEvent.title, TopicEvent.sport,
                        TopicEvent.league, TopicEvent.status, TopicEvent.summary,
                    )
                )
                .order_by(text("rank DESC"))
                .limit(200)
            )
        else:
            stmt = (
                select(TopicEvent, text("0 as rank"))
                .where(TopicEvent.workspace_id == workspace_id)
                .where(
                    or_(
                        TopicEvent.title.ilike(like),
                        TopicEvent.sport.ilike(like),
                        TopicEvent.league.ilike(like),
                        TopicEvent.status.ilike(like),
                        TopicEvent.summary.ilike(like),
                    )
                )
                .order_by(TopicEvent.updated_at.desc())
                .limit(200)
            )
        result = await self._db.execute(stmt)
        hits: list[_RawHit] = []
        for row in result.all():
            ev: TopicEvent = row[0]
            rank: float = float(row[1]) if len(row) > 1 else 0.0
            matched: list[str] = []
            if query.lower() in (ev.title or "").lower():
                matched.append("title")
            if query.lower() in (ev.sport or "").lower():
                matched.append("sport")
            if query.lower() in (ev.league or "").lower():
                matched.append("league")
            if query.lower() in (ev.status or "").lower():
                matched.append("status")
            if query.lower() in (ev.summary or "").lower():
                matched.append("summary")

            snippet_text = " / ".join(
                filter(None, [ev.title, ev.sport, ev.league, ev.status, ev.summary])
            )
            score = (
                rank
                if self._uses_tsvector(query) and rank > 0
                else _score_for(query, ev.title, matched)
            )
            hits.append(
                _RawHit(
                    entity_type="event",
                    entity_id=ev.id,
                    title=ev.title,
                    subtitle=f"{ev.sport or ''} · {ev.league or ''} · {ev.status}".strip(" ·"),
                    raw_snippet_text=snippet_text,
                    score=score,
                    matched_fields=matched,
                    sort_timestamp=ev.updated_at,
                )
            )
        return hits

    async def _search_rules(self, workspace_id: UUID, query: str) -> list[_RawHit]:
        like = f"%{query}%"
        if self._uses_tsvector(query):
            stmt = (
                select(
                    RuleSet,
                    _ts_rank(query, RuleSet.name, RuleSet.status).label("rank"),
                )
                .where(RuleSet.workspace_id == workspace_id)
                .where(_ts_match(query, RuleSet.name, RuleSet.status))
                .order_by(text("rank DESC"))
                .limit(200)
            )
        else:
            stmt = (
                select(RuleSet, text("0 as rank"))
                .where(RuleSet.workspace_id == workspace_id)
                .where(
                    or_(
                        RuleSet.name.ilike(like),
                        RuleSet.status.ilike(like),
                    )
                )
                .order_by(RuleSet.updated_at.desc())
                .limit(200)
            )
        result = await self._db.execute(stmt)
        hits: list[_RawHit] = []
        for row in result.all():
            rs: RuleSet = row[0]
            rank: float = float(row[1]) if len(row) > 1 else 0.0
            matched: list[str] = []
            if query.lower() in (rs.name or "").lower():
                matched.append("name")
            if query.lower() in (rs.status or "").lower():
                matched.append("status")

            snippet_text = " / ".join(filter(None, [rs.name, rs.status, rs.description]))
            score = (
                rank
                if self._uses_tsvector(query) and rank > 0
                else _score_for(query, rs.name, matched)
            )
            hits.append(
                _RawHit(
                    entity_type="rule",
                    entity_id=rs.id,
                    title=rs.name,
                    subtitle=f"{rs.status} · {rs.key}",
                    raw_snippet_text=snippet_text,
                    score=score,
                    matched_fields=matched,
                    sort_timestamp=rs.updated_at,
                )
            )
        return hits

    async def _search_automation_rules(self, workspace_id: UUID, query: str) -> list[_RawHit]:
        like = f"%{query}%"
        if self._uses_tsvector(query):
            stmt = (
                select(
                    AutomationRule,
                    _ts_rank(query, AutomationRule.name, AutomationRule.description).label("rank"),
                )
                .where(AutomationRule.workspace_id == workspace_id)
                .where(_ts_match(query, AutomationRule.name, AutomationRule.description))
                .order_by(text("rank DESC"))
                .limit(200)
            )
        else:
            stmt = (
                select(AutomationRule, text("0 as rank"))
                .where(AutomationRule.workspace_id == workspace_id)
                .where(
                    or_(
                        AutomationRule.name.ilike(like),
                        AutomationRule.description.ilike(like),
                    )
                )
                .order_by(AutomationRule.updated_at.desc())
                .limit(200)
            )
        result = await self._db.execute(stmt)
        hits: list[_RawHit] = []
        for row in result.all():
            rule: AutomationRule = row[0]
            rank: float = float(row[1]) if len(row) > 1 else 0.0
            matched: list[str] = []
            if query.lower() in (rule.name or "").lower():
                matched.append("name")
            if query.lower() in (rule.description or "").lower():
                matched.append("description")

            snippet_text = " / ".join(filter(None, [rule.name, rule.description]))
            score = (
                rank
                if self._uses_tsvector(query) and rank > 0
                else _score_for(query, rule.name, matched)
            )
            hits.append(
                _RawHit(
                    entity_type="automation_rule",
                    entity_id=rule.id,
                    title=rule.name,
                    subtitle=f"{rule.trigger_type} · {'enabled' if rule.enabled else 'disabled'}",
                    raw_snippet_text=snippet_text,
                    score=score,
                    matched_fields=matched,
                    sort_timestamp=rule.updated_at,
                )
            )
        return hits

    async def _search_topics(self, workspace_id: UUID, query: str) -> list[_RawHit]:
        like = f"%{query}%"
        if self._uses_tsvector(query):
            stmt = (
                select(
                    SavedTopic,
                    _ts_rank(query, SavedTopic.title, SavedTopic.summary).label("rank"),
                )
                .where(SavedTopic.workspace_id == workspace_id)
                .where(_ts_match(query, SavedTopic.title, SavedTopic.summary))
                .order_by(text("rank DESC"))
                .limit(200)
            )
        else:
            stmt = (
                select(SavedTopic, text("0 as rank"))
                .where(SavedTopic.workspace_id == workspace_id)
                .where(
                    or_(
                        SavedTopic.title.ilike(like),
                        SavedTopic.summary.ilike(like),
                    )
                )
                .order_by(SavedTopic.updated_at.desc())
                .limit(200)
            )
        result = await self._db.execute(stmt)
        hits: list[_RawHit] = []
        for row in result.all():
            topic: SavedTopic = row[0]
            rank: float = float(row[1]) if len(row) > 1 else 0.0
            matched: list[str] = []
            if query.lower() in (topic.title or "").lower():
                matched.append("title")
            if query.lower() in (topic.summary or "").lower():
                matched.append("summary")

            snippet_text = " / ".join(filter(None, [topic.title, topic.summary]))
            score = (
                rank
                if self._uses_tsvector(query) and rank > 0
                else _score_for(query, topic.title, matched)
            )
            hits.append(
                _RawHit(
                    entity_type="topic",
                    entity_id=topic.id,
                    title=topic.title,
                    subtitle=f"{topic.source_type} · {topic.status}",
                    raw_snippet_text=snippet_text,
                    score=score,
                    matched_fields=matched,
                    sort_timestamp=topic.updated_at,
                )
            )
        return hits

    async def _search_generation_runs(self, workspace_id: UUID, query: str) -> list[_RawHit]:
        like = f"%{query}%"
        if self._uses_tsvector(query):
            stmt = (
                select(
                    GenerationRun,
                    GenerationWorkflow.name.label("workflow_name"),
                    _ts_rank(query, GenerationRun.status, GenerationWorkflow.name).label("rank"),
                )
                .join(GenerationWorkflow, GenerationRun.workflow_id == GenerationWorkflow.id)
                .where(GenerationRun.workspace_id == workspace_id)
                .where(_ts_match(query, GenerationRun.status, GenerationWorkflow.name))
                .order_by(text("rank DESC"))
                .limit(200)
            )
        else:
            stmt = (
                select(
                    GenerationRun,
                    GenerationWorkflow.name.label("workflow_name"),
                    text("0 as rank"),
                )
                .join(GenerationWorkflow, GenerationRun.workflow_id == GenerationWorkflow.id)
                .where(GenerationRun.workspace_id == workspace_id)
                .where(
                    or_(
                        GenerationRun.status.ilike(like),
                        GenerationWorkflow.name.ilike(like),
                    )
                )
                .order_by(GenerationRun.updated_at.desc())
                .limit(200)
            )
        result = await self._db.execute(stmt)
        hits: list[_RawHit] = []
        for row in result.all():
            run: GenerationRun = row[0]
            workflow_name: str = row[1]
            rank: float = float(row[2]) if len(row) > 2 else 0.0
            matched: list[str] = []
            if query.lower() in (run.status or "").lower():
                matched.append("status")
            if query.lower() in (workflow_name or "").lower():
                matched.append("workflow_name")

            snippet_text = " / ".join(filter(None, [workflow_name, run.status, run.provider]))
            score = (
                rank
                if self._uses_tsvector(query) and rank > 0
                else _score_for(query, workflow_name, matched)
            )
            hits.append(
                _RawHit(
                    entity_type="generation_run",
                    entity_id=run.id,
                    title=f"{workflow_name} — {run.status}",
                    subtitle=f"{run.provider} · {run.model}",
                    raw_snippet_text=snippet_text,
                    score=score,
                    matched_fields=matched,
                    sort_timestamp=run.updated_at,
                )
            )
        return hits

    async def _search_notification_channels(
        self, workspace_id: UUID, query: str
    ) -> list[_RawHit]:
        like = f"%{query}%"
        if self._uses_tsvector(query):
            stmt = (
                select(
                    NotificationChannel,
                    _ts_rank(
                        query, NotificationChannel.name, NotificationChannel.provider_key
                    ).label("rank"),
                )
                .where(NotificationChannel.workspace_id == workspace_id)
                .where(_ts_match(query, NotificationChannel.name, NotificationChannel.provider_key))
                .order_by(text("rank DESC"))
                .limit(200)
            )
        else:
            stmt = (
                select(NotificationChannel, text("0 as rank"))
                .where(NotificationChannel.workspace_id == workspace_id)
                .where(
                    or_(
                        NotificationChannel.name.ilike(like),
                        NotificationChannel.provider_key.ilike(like),
                    )
                )
                .order_by(NotificationChannel.updated_at.desc())
                .limit(200)
            )
        result = await self._db.execute(stmt)
        hits: list[_RawHit] = []
        for row in result.all():
            ch: NotificationChannel = row[0]
            rank: float = float(row[1]) if len(row) > 1 else 0.0
            matched: list[str] = []
            if query.lower() in (ch.name or "").lower():
                matched.append("name")
            if query.lower() in (ch.provider_key or "").lower():
                matched.append("provider_key")

            snippet_text = " / ".join(filter(None, [ch.name, ch.provider_key, ch.health_status]))
            score = (
                rank
                if self._uses_tsvector(query) and rank > 0
                else _score_for(query, ch.name, matched)
            )
            hits.append(
                _RawHit(
                    entity_type="notification_channel",
                    entity_id=ch.id,
                    title=ch.name,
                    subtitle=f"{ch.provider_key} · {ch.health_status}",
                    raw_snippet_text=snippet_text,
                    score=score,
                    matched_fields=matched,
                    sort_timestamp=ch.updated_at,
                )
            )
        return hits
