from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import AutomationAction, AutomationRule
from app.models.generation import GenerationWorkflow


async def seed_automation_examples(
    session: AsyncSession, workspace_id: UUID, actor_id: UUID
) -> int:
    workflow_id = await session.scalar(
        select(GenerationWorkflow.id).where(
            GenerationWorkflow.workspace_id == workspace_id,
            GenerationWorkflow.key == "sports-short-video-full-package",
        )
    )
    examples = [
        {
            "name": "示例：作品播放量超过 100 万",
            "entity_type": "content",
            "condition_tree": {"field": "view_count", "operator": "gte", "value": 1_000_000},
            "actions": [
                (
                    "notification",
                    {
                        "channel_id": None,
                        "title": "百万播放提醒",
                        "body": "作品 {title} 已达到 {view_count} 播放。",
                    },
                )
            ],
        },
        {
            "name": "示例：作品一小时新增播放超过 10 万",
            "entity_type": "content",
            "condition_tree": {"field": "view_growth_1h", "operator": "gte", "value": 100_000},
            "actions": [
                ("create_topic", {}),
                (
                    "create_generation",
                    {
                        "workflow_id": str(workflow_id) if workflow_id else None,
                        "provider": "mock_llm",
                        "model": "mock-sports-writer-v1",
                    },
                ),
                (
                    "notification",
                    {
                        "channel_id": None,
                        "title": "高速增长作品",
                        "body": (
                            "作品一小时增长 {view_growth_1h}；"
                            "{generation_summary}{generation_error}"
                        ),
                    },
                ),
            ],
        },
        {
            "name": "示例：高热度且多来源体育事件",
            "entity_type": "news",
            "condition_tree": {
                "operator": "AND",
                "conditions": [
                    {"field": "heat_score", "operator": "gt", "value": 80},
                    {"field": "source_count", "operator": "gt", "value": 3},
                ],
            },
            "actions": [
                (
                    "notification",
                    {
                        "channel_id": None,
                        "title": "体育热点提醒",
                        "body": "热点分 {heat_score}，可靠来源数 {source_count}。",
                    },
                )
            ],
        },
    ]
    created = 0
    for example in examples:
        exists = await session.scalar(
            select(AutomationRule.id).where(
                AutomationRule.workspace_id == workspace_id,
                AutomationRule.name == example["name"],
            )
        )
        if exists is not None:
            continue
        rule = AutomationRule(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=actor_id,
            name=example["name"],
            description="系统内置示例；默认停用，配置通知渠道后方可启用。",
            entity_type=example["entity_type"],
            trigger_type="entity_updated",
            condition_tree=example["condition_tree"],
            schedule={"seed_example": True},
            cooldown_seconds=3600,
            deduplication_window=3600,
            enabled=False,
            priority=100,
        )
        rule.actions = [
            AutomationAction(
                id=uuid4(),
                workspace_id=workspace_id,
                rule_id=rule.id,
                action_type=action_type,
                config=config,
                sort_order=index,
                enabled=True,
            )
            for index, (action_type, config) in enumerate(example["actions"])
        ]
        session.add(rule)
        created += 1
    await session.commit()
    return created
