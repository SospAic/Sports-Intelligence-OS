"""Cross-platform same-topic clustering and language normalization.

Groups trend videos and news articles across platforms by topic similarity.
Uses entity extraction (teams, players, events) as the primary matching signal.

IMPORTANT: Does NOT auto-merge. Creates "suggested_links" with a confidence
score that require human confirmation before being treated as the same event.
Cross-language similar titles are never automatically merged into the same
factual event without reliable entity linking and human confirmation.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import TopicEvent
from app.models.trends import CrossPlatformLink, TrendVideo
from app.providers.news.utils import title_similarity
from app.services.entity_extraction import (
    ExtractedEntity,
    compute_entity_similarity,
    extract_entities,
)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Cross-language matches require BOTH entity overlap >= 2 AND title_similarity >= 0.6
MIN_ENTITY_OVERLAP_CROSS_LANG = 2
MIN_TITLE_SIMILARITY_CROSS_LANG = 0.6

# Same-language matches are slightly more lenient
MIN_ENTITY_OVERLAP_SAME_LANG = 1
MIN_TITLE_SIMILARITY_SAME_LANG = 0.5

# Minimum confidence to create a suggested link
MIN_SUGGESTION_CONFIDENCE = 0.4

# Lookback window for clustering candidates
CLUSTER_LOOKBACK_HOURS = 72


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")
_LATIN_RE = re.compile(r"[a-zA-Z]")


def detect_language(text: str) -> str:
    """Detect whether text is primarily Chinese or English.

    Returns 'zh', 'en', or 'mixed'.
    """
    cjk_count = len(_CJK_RE.findall(text))
    latin_count = len(_LATIN_RE.findall(text))
    if cjk_count == 0 and latin_count == 0:
        return "unknown"
    if cjk_count > latin_count * 0.5:
        return "zh"
    if latin_count > cjk_count * 2:
        return "en"
    return "mixed"


def normalize_for_comparison(title: str) -> str:
    """Normalize a title for cross-language comparison.

    Stores a normalized form suitable for comparison without replacing the
    original. For Chinese text, extracts CJK characters and key entities.
    For English text, lowercases and strips punctuation.
    """
    import unicodedata

    normalized = unicodedata.normalize("NFKC", title).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


# ---------------------------------------------------------------------------
# Entity overlap counting
# ---------------------------------------------------------------------------


def count_entity_overlap(
    entities_a: list[ExtractedEntity],
    entities_b: list[ExtractedEntity],
) -> int:
    """Count the number of shared entities between two entity lists.

    Matches by canonical form (lowercase text + type).
    """
    set_a = {(e.text.lower().strip(), e.entity_type) for e in entities_a}
    set_b = {(e.text.lower().strip(), e.entity_type) for e in entities_b}
    return len(set_a & set_b)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CrossPlatformClusterService:
    """Cross-platform same-topic clustering service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run_clustering(
        self,
        workspace_id: UUID,
        *,
        lookback_hours: int = CLUSTER_LOOKBACK_HOURS,
        limit: int = 200,
    ) -> list[CrossPlatformLink]:
        """Run cross-platform clustering and create suggested links.

        Compares trend videos and news events across different platforms.
        Does NOT auto-merge — only creates suggestions with confidence scores.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)

        # Load recent trend videos
        videos = list(
            (
                await self.session.scalars(
                    select(TrendVideo)
                    .where(
                        TrendVideo.workspace_id == workspace_id,
                        TrendVideo.observed_at >= cutoff,
                    )
                    .order_by(TrendVideo.observed_at.desc())
                    .limit(limit)
                )
            ).all()
        )

        # Load recent topic events
        events = list(
            (
                await self.session.scalars(
                    select(TopicEvent)
                    .where(
                        TopicEvent.workspace_id == workspace_id,
                        TopicEvent.last_update_time >= cutoff,
                        TopicEvent.status == "active",
                    )
                    .order_by(TopicEvent.last_update_time.desc())
                    .limit(limit)
                )
            ).all()
        )

        # Build entity cache for all items
        video_entities: dict[UUID, list[ExtractedEntity]] = {}
        video_langs: dict[UUID, str] = {}
        for video in videos:
            video_entities[video.id] = extract_entities(video.title)
            video_langs[video.id] = detect_language(video.title)

        event_entities: dict[UUID, list[ExtractedEntity]] = {}
        event_langs: dict[UUID, str] = {}
        for event in events:
            # Use entities from metadata if available, otherwise extract
            meta_entities = (event.metadata_json or {}).get("extracted_entities", [])
            if meta_entities:
                from app.services.entity_extraction import EntityType

                parsed = []
                for raw in meta_entities:
                    try:
                        parsed.append(
                            ExtractedEntity(
                                text=raw["text"],
                                entity_type=EntityType(raw["type"]),
                                confidence=raw.get("confidence", 0.8),
                            )
                        )
                    except (KeyError, ValueError):
                        continue
                event_entities[event.id] = parsed
            else:
                event_entities[event.id] = extract_entities(event.title)
            event_langs[event.id] = detect_language(event.title)

        # Load existing links to avoid duplicates
        existing_links = set()
        existing = list(
            (
                await self.session.scalars(
                    select(CrossPlatformLink).where(
                        CrossPlatformLink.workspace_id == workspace_id,
                        CrossPlatformLink.status != "rejected",
                    )
                )
            ).all()
        )
        for existing_link in existing:
            existing_links.add(
                (str(existing_link.source_entity_id), str(existing_link.target_entity_id))
            )
            existing_links.add(
                (str(existing_link.target_entity_id), str(existing_link.source_entity_id))
            )

        new_links: list[CrossPlatformLink] = []

        # Compare videos across different platforms
        for i, video_a in enumerate(videos):
            for video_b in videos[i + 1 :]:
                # Only cross-platform comparisons
                if video_a.platform == video_b.platform:
                    continue
                pair_key = (str(video_a.id), str(video_b.id))
                if pair_key in existing_links:
                    continue

                link = self._evaluate_pair(
                    workspace_id=workspace_id,
                    source_type="trend_video",
                    source_id=video_a.id,
                    source_title=video_a.title,
                    source_platform=video_a.platform,
                    source_entities=video_entities[video_a.id],
                    source_lang=video_langs[video_a.id],
                    target_type="trend_video",
                    target_id=video_b.id,
                    target_title=video_b.title,
                    target_platform=video_b.platform,
                    target_entities=video_entities[video_b.id],
                    target_lang=video_langs[video_b.id],
                )
                if link is not None:
                    new_links.append(link)
                    existing_links.add(pair_key)

        # Compare videos vs events (cross-type)
        for video in videos:
            for event in events:
                pair_key = (str(video.id), str(event.id))
                if pair_key in existing_links:
                    continue

                link = self._evaluate_pair(
                    workspace_id=workspace_id,
                    source_type="trend_video",
                    source_id=video.id,
                    source_title=video.title,
                    source_platform=video.platform,
                    source_entities=video_entities[video.id],
                    source_lang=video_langs[video.id],
                    target_type="topic_event",
                    target_id=event.id,
                    target_title=event.title,
                    target_platform="news",
                    target_entities=event_entities[event.id],
                    target_lang=event_langs[event.id],
                )
                if link is not None:
                    new_links.append(link)
                    existing_links.add(pair_key)

        # Persist new links
        for link in new_links:
            self.session.add(link)
        if new_links:
            await self.session.flush()

        return new_links

    def _evaluate_pair(
        self,
        *,
        workspace_id: UUID,
        source_type: str,
        source_id: UUID,
        source_title: str,
        source_platform: str,
        source_entities: list[ExtractedEntity],
        source_lang: str,
        target_type: str,
        target_id: UUID,
        target_title: str,
        target_platform: str,
        target_entities: list[ExtractedEntity],
        target_lang: str,
    ) -> CrossPlatformLink | None:
        """Evaluate a pair of entities and return a link if they pass thresholds."""
        # Compute title similarity
        sim = title_similarity(source_title, target_title)

        # Compute entity overlap and similarity
        overlap = count_entity_overlap(source_entities, target_entities)
        entity_sim = compute_entity_similarity(source_entities, target_entities)

        # Determine if cross-language
        is_cross_lang = (
            source_lang != target_lang and source_lang != "mixed" and target_lang != "mixed"
        )

        # Apply thresholds
        if is_cross_lang:
            if overlap < MIN_ENTITY_OVERLAP_CROSS_LANG:
                return None
            if sim < MIN_TITLE_SIMILARITY_CROSS_LANG:
                return None
        else:
            if overlap < MIN_ENTITY_OVERLAP_SAME_LANG and sim < MIN_TITLE_SIMILARITY_SAME_LANG:
                return None

        # Compute confidence score
        confidence = self._compute_confidence(
            title_sim=sim,
            entity_overlap=overlap,
            entity_sim=entity_sim,
            is_cross_lang=is_cross_lang,
        )

        if confidence < MIN_SUGGESTION_CONFIDENCE:
            return None

        return CrossPlatformLink(
            id=uuid4(),
            workspace_id=workspace_id,
            source_entity_type=source_type,
            source_entity_id=source_id,
            target_entity_type=target_type,
            target_entity_id=target_id,
            confidence=round(confidence, 4),
            status="suggested",
            match_details_json={
                "title_similarity": round(sim, 4),
                "entity_overlap": overlap,
                "entity_similarity": round(entity_sim, 4),
                "is_cross_language": is_cross_lang,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "source_platform": source_platform,
                "target_platform": target_platform,
                "source_title": source_title[:200],
                "target_title": target_title[:200],
                "algorithm": "cross-platform-entity-v1",
                "note": (
                    "跨语言匹配：需要可靠实体链接和人工确认，不自动合并"
                    if is_cross_lang
                    else "同语言匹配：建议人工确认后合并"
                ),
            },
        )

    @staticmethod
    def _compute_confidence(
        *,
        title_sim: float,
        entity_overlap: int,
        entity_sim: float,
        is_cross_lang: bool,
    ) -> float:
        """Compute a confidence score for a cross-platform match.

        Cross-language matches are penalized to reflect higher uncertainty.
        """
        # Base confidence from weighted signals
        base = 0.35 * title_sim + 0.40 * entity_sim + 0.25 * min(entity_overlap / 4.0, 1.0)

        # Cross-language penalty: reduce confidence by 20%
        if is_cross_lang:
            base *= 0.80

        return min(1.0, max(0.0, base))

    # ------------------------------------------------------------------
    # Link management
    # ------------------------------------------------------------------

    async def list_links(
        self,
        workspace_id: UUID,
        *,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[CrossPlatformLink], int]:
        """List cross-platform links with optional status filter."""
        stmt = select(CrossPlatformLink).where(
            CrossPlatformLink.workspace_id == workspace_id,
        )
        if status:
            stmt = stmt.where(CrossPlatformLink.status == status)

        # Count total
        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.scalar(count_stmt)) or 0

        # Paginate
        stmt = (
            stmt.order_by(CrossPlatformLink.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(stmt)).all())
        return items, total

    async def confirm_link(self, workspace_id: UUID, link_id: UUID) -> CrossPlatformLink:
        """Confirm a suggested cross-platform link."""
        from fastapi import HTTPException

        link = await self.session.get(CrossPlatformLink, link_id)
        if link is None or link.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="跨平台关联未找到")
        if link.status != "suggested":
            raise HTTPException(
                status_code=409,
                detail=f"关联状态为 {link.status}，无法确认",
            )
        link.status = "confirmed"
        await self.session.flush()
        return link

    async def reject_link(self, workspace_id: UUID, link_id: UUID) -> CrossPlatformLink:
        """Reject a suggested cross-platform link."""
        from fastapi import HTTPException

        link = await self.session.get(CrossPlatformLink, link_id)
        if link is None or link.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="跨平台关联未找到")
        if link.status != "suggested":
            raise HTTPException(
                status_code=409,
                detail=f"关联状态为 {link.status}，无法拒绝",
            )
        link.status = "rejected"
        await self.session.flush()
        return link
