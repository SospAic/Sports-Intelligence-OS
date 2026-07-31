#!/usr/bin/env python3
"""
离线重聚类维护工具 — Sports Intelligence OS

为历史文章提供"预览、人工确认、执行、可回滚"的离线重聚类能力。
本工具是离线维护脚本，不会自动执行任何破坏性操作。

使用方式:
    # 1. 预览：分析所有文章，生成聚类提案（不修改数据库）
    python scripts/recluster_articles.py --preview

    # 2. 执行：根据提案文件重新聚类（会先备份旧状态）
    python scripts/recluster_articles.py --execute [--proposal data/recluster_proposal_YYYYMMDD.json]

    # 3. 回滚：恢复到执行前的状态
    python scripts/recluster_articles.py --rollback [--backup data/recluster_backup_YYYYMMDD.json]

环境变量:
    SIO_DATABASE_URL  PostgreSQL 连接字符串
                      默认: postgresql+asyncpg://sio:sio-local-development-only@127.0.0.1:5432/sports_intelligence
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup: allow importing from apps/api
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_ROOT = PROJECT_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models.news import Article, EventArticle, TopicEvent  # noqa: E402
from app.providers.news.utils import normalize_title, title_similarity  # noqa: E402
from app.services.entity_extraction import (  # noqa: E402
    EntityType,
    ExtractedEntity,
    compute_entity_similarity,
    extract_article_entities,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://sio:sio-local-development-only@127.0.0.1:5432/sports_intelligence"
)
DATA_DIR = PROJECT_ROOT / "data"
EVENT_SIMILARITY_THRESHOLD = 0.62
TITLE_WEIGHT = 0.65
ENTITY_WEIGHT = 0.35
STRONG_ENTITY_THRESHOLD = 0.7
STRONG_ENTITY_TITLE_MIN = 0.2
STRONG_ENTITY_WEIGHT = 0.85


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_database_url() -> str:
    import os

    return os.environ.get("SIO_DATABASE_URL", DEFAULT_DATABASE_URL)


def today_stamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def print_header(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}\n")


def print_info(msg: str) -> None:
    print(f"  [信息] {msg}")


def print_warn(msg: str) -> None:
    print(f"  [警告] {msg}")


def print_error(msg: str) -> None:
    print(f"  [错误] {msg}", file=sys.stderr)


def print_success(msg: str) -> None:
    print(f"  [完成] {msg}")


# ---------------------------------------------------------------------------
# Clustering algorithm (mirrors NewsService._cluster_article logic)
# ---------------------------------------------------------------------------


def compute_match_score(
    article_title: str,
    article_entities: list[ExtractedEntity],
    event_title: str,
    event_entities: list[ExtractedEntity],
) -> tuple[float, dict[str, float]]:
    """Compute the clustering match score between an article and an event.

    Returns (score, components) where components breaks down the scoring.
    """
    title_score = title_similarity(event_title, article_title)
    entity_score = (
        compute_entity_similarity(article_entities, event_entities)
        if event_entities
        else 0.0
    )
    weighted_score = title_score * TITLE_WEIGHT + entity_score * ENTITY_WEIGHT
    strong_entity_score = (
        entity_score * STRONG_ENTITY_WEIGHT
        if entity_score >= STRONG_ENTITY_THRESHOLD and title_score >= STRONG_ENTITY_TITLE_MIN
        else 0.0
    )
    score = max(title_score, weighted_score, strong_entity_score)
    components = {
        "title": round(title_score, 4),
        "entity": round(entity_score, 4),
        "combined": round(score, 4),
    }
    return score, components


def parse_event_entities(metadata: dict[str, Any]) -> list[ExtractedEntity]:
    """Parse stored entity data from event metadata back into ExtractedEntity objects."""
    raw_entities = metadata.get("extracted_entities", [])
    entities: list[ExtractedEntity] = []
    for raw in raw_entities:
        try:
            entities.append(
                ExtractedEntity(
                    text=raw["text"],
                    entity_type=EntityType(raw["type"]),
                    confidence=raw["confidence"],
                )
            )
        except (KeyError, ValueError):
            continue
    return entities


async def run_clustering(
    session: AsyncSession,
) -> dict[str, Any]:
    """Run the improved clustering algorithm over all articles.

    Returns a proposal dict describing what would change.
    """
    # Load all articles
    articles_result = await session.execute(select(Article).order_by(Article.fetched_at))
    articles: list[Article] = list(articles_result.scalars().all())
    print_info(f"已加载 {len(articles)} 篇文章")

    # Load all existing events
    events_result = await session.execute(select(TopicEvent))
    events: list[TopicEvent] = list(events_result.scalars().all())
    print_info(f"已加载 {len(events)} 个现有事件")

    # Load existing event-article links
    links_result = await session.execute(select(EventArticle))
    existing_links: list[EventArticle] = list(links_result.scalars().all())
    current_assignments: dict[str, str] = {
        str(link.article_id): str(link.event_id) for link in existing_links
    }
    print_info(f"已加载 {len(existing_links)} 条现有文章-事件关联")

    # Pre-compute event entities
    event_entities_map: dict[str, list[ExtractedEntity]] = {}
    for event in events:
        event_entities_map[str(event.id)] = parse_event_entities(event.metadata_json or {})

    # Run clustering: assign each article to best matching event or create new
    new_assignments: dict[str, dict[str, Any]] = {}  # article_id -> {event_id, score, components, is_new_event}
    proposed_new_events: list[dict[str, Any]] = []
    # Track events created during this clustering pass (title -> event info)
    runtime_events: list[dict[str, Any]] = [
        {
            "id": str(e.id),
            "title": e.title,
            "entities": event_entities_map[str(e.id)],
            "is_existing": True,
        }
        for e in events
    ]

    for idx, article in enumerate(articles):
        if (idx + 1) % 50 == 0:
            print_info(f"正在处理第 {idx + 1}/{len(articles)} 篇文章...")

        article_entities = extract_article_entities(article.title, article.summary or "")
        best_event_id: str | None = None
        best_score = 0.0
        best_components: dict[str, float] = {}

        for rev in runtime_events:
            score, components = compute_match_score(
                article.title,
                article_entities,
                rev["title"],
                rev["entities"],
            )
            if score >= EVENT_SIMILARITY_THRESHOLD and score > best_score:
                best_event_id = rev["id"]
                best_score = score
                best_components = components

        if best_event_id is None:
            # Create a new event for this article
            new_event_id = str(uuid.uuid4())
            entity_data = [
                {"text": e.text, "type": e.entity_type.value, "confidence": round(e.confidence, 2)}
                for e in article_entities
            ]
            new_event_info = {
                "id": new_event_id,
                "title": article.title,
                "entities": article_entities,
                "is_existing": False,
            }
            runtime_events.append(new_event_info)
            proposed_new_events.append({
                "id": new_event_id,
                "title": article.title,
                "normalized_title": normalize_title(article.title),
                "summary": article.summary,
                "sport": article.sport,
                "league": article.league,
                "metadata_json": {
                    "cluster_algorithm": "entity-enhanced-v2",
                    "extracted_entities": entity_data,
                    "created_by": "offline_recluster",
                },
            })
            best_event_id = new_event_id
            best_score = 1.0
            best_components = {"title": 1.0, "entity": 1.0, "combined": 1.0}

        new_assignments[str(article.id)] = {
            "event_id": best_event_id,
            "score": round(best_score, 4),
            "components": best_components,
            "article_title": article.title,
        }

    # Compute changes
    changes = _compute_changes(current_assignments, new_assignments, events)

    proposal = {
        "generated_at": datetime.now(UTC).isoformat(),
        "algorithm": "entity-enhanced-v2",
        "threshold": EVENT_SIMILARITY_THRESHOLD,
        "stats": {
            "total_articles": len(articles),
            "existing_events": len(events),
            "proposed_new_events": len(proposed_new_events),
            "articles_moved": changes["moved_count"],
            "articles_unchanged": changes["unchanged_count"],
            "events_to_close": len(changes["events_to_close"]),
        },
        "changes": changes,
        "new_events": proposed_new_events,
        "assignments": new_assignments,
    }
    return proposal


def _compute_changes(
    current: dict[str, str],
    proposed: dict[str, dict[str, Any]],
    events: list[TopicEvent],
) -> dict[str, Any]:
    """Compare current vs proposed assignments and summarize changes."""
    moved: list[dict[str, Any]] = []
    unchanged = 0
    events_to_close: list[str] = []

    # Events that will have zero articles after re-clustering
    proposed_event_ids = {info["event_id"] for info in proposed.values()}

    for article_id, info in proposed.items():
        old_event_id = current.get(article_id)
        new_event_id = info["event_id"]
        if old_event_id == new_event_id:
            unchanged += 1
        else:
            moved.append({
                "article_id": article_id,
                "article_title": info["article_title"],
                "old_event_id": old_event_id,
                "new_event_id": new_event_id,
                "score": info["score"],
                "components": info["components"],
            })

    # Find existing events that would lose all their articles
    for event in events:
        eid = str(event.id)
        if eid not in proposed_event_ids and eid in set(current.values()):
            events_to_close.append(eid)

    return {
        "moved": moved,
        "moved_count": len(moved),
        "unchanged_count": unchanged,
        "events_to_close": events_to_close,
    }


# ---------------------------------------------------------------------------
# Mode: Preview
# ---------------------------------------------------------------------------


async def mode_preview(database_url: str) -> None:
    print_header("离线重聚类工具 — 预览模式")
    print_info("本模式不会修改数据库，仅生成聚类提案文件。")
    print_info(f"数据库: {database_url.split('@')[-1] if '@' in database_url else database_url}")
    print()

    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # Verify connectivity
            await session.execute(text("SELECT 1"))
            print_info("数据库连接成功")

            proposal = await run_clustering(session)
    finally:
        await engine.dispose()

    # Print summary
    stats = proposal["stats"]
    print_header("聚类分析结果摘要")
    print(f"  文章总数:         {stats['total_articles']}")
    print(f"  现有事件数:       {stats['existing_events']}")
    print(f"  建议新建事件数:   {stats['proposed_new_events']}")
    print(f"  文章将移动数:     {stats['articles_moved']}")
    print(f"  文章保持不变数:   {stats['articles_unchanged']}")
    print(f"  将关闭的事件数:   {stats['events_to_close']}")
    print()

    # Show sample of moves
    moves = proposal["changes"]["moved"]
    if moves:
        print_info(f"以下为前 20 条移动示例（共 {len(moves)} 条）:")
        print(f"  {'文章标题':<40} {'得分':<8} {'标题分':<8} {'实体分':<8}")
        print(f"  {'-'*40} {'-'*8} {'-'*8} {'-'*8}")
        for m in moves[:20]:
            title_display = m["article_title"][:38] + ".." if len(m["article_title"]) > 40 else m["article_title"]
            comp = m["components"]
            print(f"  {title_display:<40} {comp['combined']:<8.4f} {comp['title']:<8.4f} {comp['entity']:<8.4f}")
        print()

    # Save proposal
    ensure_data_dir()
    proposal_path = DATA_DIR / f"recluster_proposal_{today_stamp()}.json"
    with open(proposal_path, "w", encoding="utf-8") as f:
        json.dump(proposal, f, ensure_ascii=False, indent=2)

    print_success(f"提案已保存至: {proposal_path}")
    print_info("请人工审核提案内容。确认无误后，使用以下命令执行:")
    print(f"    python scripts/recluster_articles.py --execute --proposal \"{proposal_path}\"")
    print()


# ---------------------------------------------------------------------------
# Mode: Execute
# ---------------------------------------------------------------------------


async def mode_execute(database_url: str, proposal_path: Path) -> None:
    print_header("离线重聚类工具 — 执行模式")

    if not proposal_path.exists():
        print_error(f"提案文件不存在: {proposal_path}")
        sys.exit(1)

    with open(proposal_path, "r", encoding="utf-8") as f:
        proposal = json.load(f)

    stats = proposal["stats"]
    print_info(f"提案生成时间: {proposal['generated_at']}")
    print_info(f"算法: {proposal['algorithm']}  阈值: {proposal['threshold']}")
    print(f"  将移动文章:     {stats['articles_moved']} 篇")
    print(f"  将新建事件:     {stats['proposed_new_events']} 个")
    print(f"  将关闭事件:     {stats['events_to_close']} 个")
    print()

    # Human confirmation
    print_warn("此操作将修改数据库中的事件聚类关系！")
    print_warn("执行前会自动备份当前状态，可通过 --rollback 回滚。")
    answer = input("\n  确认执行？输入 YES 继续: ").strip()
    if answer != "YES":
        print_info("已取消执行。")
        return

    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
            print_info("数据库连接成功")

            # --- Step 1: Backup current state ---
            print_info("正在备份当前状态...")
            backup = await _create_backup(session)
            ensure_data_dir()
            backup_path = DATA_DIR / f"recluster_backup_{today_stamp()}.json"
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(backup, f, ensure_ascii=False, indent=2)
            print_success(f"备份已保存至: {backup_path}")

            # --- Step 2: Create new events ---
            new_events = proposal.get("new_events", [])
            if new_events:
                print_info(f"正在创建 {len(new_events)} 个新事件...")
                now = datetime.now(UTC)
                for ev_data in new_events:
                    event = TopicEvent(
                        id=uuid.UUID(ev_data["id"]),
                        workspace_id=backup["workspace_id"],
                        title=ev_data["title"],
                        normalized_title=ev_data["normalized_title"],
                        summary=ev_data.get("summary"),
                        sport=ev_data.get("sport"),
                        league=ev_data.get("league"),
                        start_time=now,
                        last_update_time=now,
                        article_count=0,
                        source_count=0,
                        heat_score=Decimal("0"),
                        reliability_score=Decimal("0"),
                        controversy_score=Decimal("0"),
                        visual_score=Decimal("0"),
                        story_score=Decimal("0"),
                        status="active",
                        metadata_json=ev_data.get("metadata_json", {}),
                        is_bookmarked=False,
                        bookmarked_at=None,
                    )
                    session.add(event)
                await session.flush()
                print_success(f"已创建 {len(new_events)} 个新事件")

            # --- Step 3: Remove old event-article links ---
            print_info("正在清除旧的文章-事件关联...")
            old_links_result = await session.execute(select(EventArticle))
            old_links = list(old_links_result.scalars().all())
            for link in old_links:
                await session.delete(link)
            await session.flush()
            print_success(f"已清除 {len(old_links)} 条旧关联")

            # --- Step 4: Create new event-article links ---
            assignments = proposal.get("assignments", {})
            print_info(f"正在创建 {len(assignments)} 条新关联...")
            now = datetime.now(UTC)
            for article_id_str, info in assignments.items():
                link = EventArticle(
                    id=uuid.uuid4(),
                    event_id=uuid.UUID(info["event_id"]),
                    article_id=uuid.UUID(article_id_str),
                    match_score=Decimal(str(info["score"])),
                    linked_by="offline_recluster",
                    created_at=now,
                )
                session.add(link)
            await session.flush()
            print_success(f"已创建 {len(assignments)} 条新关联")

            # --- Step 5: Close orphaned events ---
            events_to_close = proposal["changes"].get("events_to_close", [])
            if events_to_close:
                print_info(f"正在关闭 {len(events_to_close)} 个孤立事件...")
                for event_id_str in events_to_close:
                    event = await session.get(TopicEvent, uuid.UUID(event_id_str))
                    if event:
                        event.status = "closed"
                        event.metadata_json = {
                            **(event.metadata_json or {}),
                            "closed_by": "offline_recluster",
                            "closed_at": now.isoformat(),
                        }
                await session.flush()
                print_success(f"已关闭 {len(events_to_close)} 个事件")

            # --- Step 6: Recalculate event stats ---
            print_info("正在重新计算事件统计...")
            all_events_result = await session.execute(
                select(TopicEvent).where(TopicEvent.status != "closed")
            )
            active_events = list(all_events_result.scalars().all())
            for event in active_events:
                await _recalculate_event_stats(session, event)
            await session.flush()
            print_success(f"已重新计算 {len(active_events)} 个活跃事件的统计")

            # --- Commit ---
            await session.commit()
            print_success("所有更改已提交到数据库")

    except Exception as exc:
        print_error(f"执行过程中发生错误: {exc}")
        print_info("事务已回滚，数据库未被修改。")
        raise
    finally:
        await engine.dispose()

    print()
    print_success("重聚类执行完毕！")
    print_info(f"如需回滚，请使用: python scripts/recluster_articles.py --rollback --backup \"{backup_path}\"")
    print()


async def _create_backup(session: AsyncSession) -> dict[str, Any]:
    """Backup the current event-article links and event states."""
    links_result = await session.execute(select(EventArticle))
    links = list(links_result.scalars().all())

    events_result = await session.execute(select(TopicEvent))
    events = list(events_result.scalars().all())

    # Determine workspace_id from first event
    workspace_id = str(events[0].workspace_id) if events else None

    backup = {
        "created_at": datetime.now(UTC).isoformat(),
        "workspace_id": workspace_id,
        "event_articles": [
            {
                "id": str(link.id),
                "event_id": str(link.event_id),
                "article_id": str(link.article_id),
                "match_score": str(link.match_score),
                "linked_by": link.linked_by,
                "created_at": link.created_at.isoformat() if link.created_at else None,
            }
            for link in links
        ],
        "events": [
            {
                "id": str(e.id),
                "title": e.title,
                "normalized_title": e.normalized_title,
                "summary": e.summary,
                "sport": e.sport,
                "league": e.league,
                "start_time": e.start_time.isoformat() if e.start_time else None,
                "last_update_time": e.last_update_time.isoformat() if e.last_update_time else None,
                "article_count": e.article_count,
                "source_count": e.source_count,
                "heat_score": str(e.heat_score),
                "reliability_score": str(e.reliability_score),
                "controversy_score": str(e.controversy_score),
                "visual_score": str(e.visual_score),
                "story_score": str(e.story_score),
                "status": e.status,
                "metadata_json": e.metadata_json,
                "is_bookmarked": e.is_bookmarked,
                "bookmarked_at": e.bookmarked_at.isoformat() if e.bookmarked_at else None,
            }
            for e in events
        ],
    }
    return backup


async def _recalculate_event_stats(session: AsyncSession, event: TopicEvent) -> None:
    """Recalculate article_count and source_count for an event."""
    links_result = await session.execute(
        select(EventArticle).where(EventArticle.event_id == event.id)
    )
    links = list(links_result.scalars().all())
    event.article_count = len(links)

    if links:
        article_ids = [link.article_id for link in links]
        articles_result = await session.execute(
            select(Article).where(Article.id.in_(article_ids))
        )
        articles = list(articles_result.scalars().all())
        unique_sources = {a.source_id for a in articles}
        event.source_count = len(unique_sources)
        # Update last_update_time
        fetched_times = [a.fetched_at for a in articles if a.fetched_at]
        if fetched_times:
            event.last_update_time = max(fetched_times)
    else:
        event.source_count = 0


# ---------------------------------------------------------------------------
# Mode: Rollback
# ---------------------------------------------------------------------------


async def mode_rollback(database_url: str, backup_path: Path) -> None:
    print_header("离线重聚类工具 — 回滚模式")

    if not backup_path.exists():
        print_error(f"备份文件不存在: {backup_path}")
        sys.exit(1)

    with open(backup_path, "r", encoding="utf-8") as f:
        backup = json.load(f)

    link_count = len(backup.get("event_articles", []))
    event_count = len(backup.get("events", []))
    print_info(f"备份创建时间: {backup['created_at']}")
    print_info(f"备份包含: {link_count} 条文章-事件关联, {event_count} 个事件")
    print()

    print_warn("此操作将：")
    print_warn("  1. 删除所有当前文章-事件关联")
    print_warn("  2. 删除重聚类期间新建的事件")
    print_warn("  3. 恢复备份中的关联和事件状态")
    answer = input("\n  确认回滚？输入 YES 继续: ").strip()
    if answer != "YES":
        print_info("已取消回滚。")
        return

    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
            print_info("数据库连接成功")

            # --- Step 1: Delete all current event-article links ---
            print_info("正在清除当前所有文章-事件关联...")
            current_links_result = await session.execute(select(EventArticle))
            current_links = list(current_links_result.scalars().all())
            for link in current_links:
                await session.delete(link)
            await session.flush()
            print_success(f"已清除 {len(current_links)} 条当前关联")

            # --- Step 2: Delete events created by recluster (not in backup) ---
            backup_event_ids = {e["id"] for e in backup.get("events", [])}
            all_events_result = await session.execute(select(TopicEvent))
            all_events = list(all_events_result.scalars().all())
            deleted_count = 0
            for event in all_events:
                if str(event.id) not in backup_event_ids:
                    await session.delete(event)
                    deleted_count += 1
            await session.flush()
            if deleted_count:
                print_success(f"已删除 {deleted_count} 个重聚类期间新建的事件")

            # --- Step 3: Restore event states from backup ---
            print_info("正在恢复事件状态...")
            for ev_data in backup.get("events", []):
                event = await session.get(TopicEvent, uuid.UUID(ev_data["id"]))
                if event:
                    event.title = ev_data["title"]
                    event.normalized_title = ev_data["normalized_title"]
                    event.summary = ev_data.get("summary")
                    event.sport = ev_data.get("sport")
                    event.league = ev_data.get("league")
                    event.start_time = (
                        datetime.fromisoformat(ev_data["start_time"])
                        if ev_data.get("start_time")
                        else None
                    )
                    event.last_update_time = (
                        datetime.fromisoformat(ev_data["last_update_time"])
                        if ev_data.get("last_update_time")
                        else datetime.now(UTC)
                    )
                    event.article_count = ev_data["article_count"]
                    event.source_count = ev_data["source_count"]
                    event.heat_score = Decimal(ev_data["heat_score"])
                    event.reliability_score = Decimal(ev_data["reliability_score"])
                    event.controversy_score = Decimal(ev_data["controversy_score"])
                    event.visual_score = Decimal(ev_data["visual_score"])
                    event.story_score = Decimal(ev_data["story_score"])
                    event.status = ev_data["status"]
                    event.metadata_json = ev_data.get("metadata_json", {})
                    event.is_bookmarked = ev_data.get("is_bookmarked", False)
                    event.bookmarked_at = (
                        datetime.fromisoformat(ev_data["bookmarked_at"])
                        if ev_data.get("bookmarked_at")
                        else None
                    )
            await session.flush()
            print_success(f"已恢复 {len(backup.get('events', []))} 个事件的状态")

            # --- Step 4: Restore event-article links ---
            print_info("正在恢复文章-事件关联...")
            for link_data in backup.get("event_articles", []):
                link = EventArticle(
                    id=uuid.UUID(link_data["id"]),
                    event_id=uuid.UUID(link_data["event_id"]),
                    article_id=uuid.UUID(link_data["article_id"]),
                    match_score=Decimal(link_data["match_score"]),
                    linked_by=link_data["linked_by"],
                    created_at=(
                        datetime.fromisoformat(link_data["created_at"])
                        if link_data.get("created_at")
                        else datetime.now(UTC)
                    ),
                )
                session.add(link)
            await session.flush()
            print_success(f"已恢复 {link_count} 条文章-事件关联")

            # --- Commit ---
            await session.commit()
            print_success("回滚已提交到数据库")

    except Exception as exc:
        print_error(f"回滚过程中发生错误: {exc}")
        print_info("事务已回滚，数据库未被修改。")
        raise
    finally:
        await engine.dispose()

    print()
    print_success("回滚完毕！数据库已恢复到重聚类前的状态。")
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def find_latest_file(pattern_prefix: str) -> Path | None:
    """Find the most recent file matching a prefix in the data directory."""
    if not DATA_DIR.exists():
        return None
    candidates = sorted(DATA_DIR.glob(f"{pattern_prefix}_*.json"), reverse=True)
    return candidates[0] if candidates else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sports Intelligence OS 离线重聚类维护工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/recluster_articles.py --preview
  python scripts/recluster_articles.py --execute
  python scripts/recluster_articles.py --execute --proposal data/recluster_proposal_20260101.json
  python scripts/recluster_articles.py --rollback
  python scripts/recluster_articles.py --rollback --backup data/recluster_backup_20260101.json
        """,
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--preview",
        action="store_true",
        help="预览模式：分析文章并生成聚类提案（不修改数据库）",
    )
    mode_group.add_argument(
        "--execute",
        action="store_true",
        help="执行模式：根据提案执行重聚类（需人工确认）",
    )
    mode_group.add_argument(
        "--rollback",
        action="store_true",
        help="回滚模式：恢复到执行前的状态（需人工确认）",
    )
    parser.add_argument(
        "--proposal",
        type=str,
        default=None,
        help="提案文件路径（默认自动查找 data/ 下最新的提案文件）",
    )
    parser.add_argument(
        "--backup",
        type=str,
        default=None,
        help="备份文件路径（默认自动查找 data/ 下最新的备份文件）",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="数据库连接字符串（默认使用 SIO_DATABASE_URL 环境变量）",
    )

    args = parser.parse_args()
    database_url = args.database_url or get_database_url()

    if args.preview:
        asyncio.run(mode_preview(database_url))
    elif args.execute:
        proposal_path = (
            Path(args.proposal)
            if args.proposal
            else find_latest_file("recluster_proposal")
        )
        if proposal_path is None:
            print_error("未找到提案文件。请先运行 --preview 生成提案。")
            sys.exit(1)
        asyncio.run(mode_execute(database_url, proposal_path))
    elif args.rollback:
        backup_path = (
            Path(args.backup)
            if args.backup
            else find_latest_file("recluster_backup")
        )
        if backup_path is None:
            print_error("未找到备份文件。只有在执行过 --execute 后才能回滚。")
            sys.exit(1)
        asyncio.run(mode_rollback(database_url, backup_path))


if __name__ == "__main__":
    main()
