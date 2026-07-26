from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.editorial_rules import RuleSet, RuleSetVersion
from app.models.generation import GenerationWorkflow, PromptCollection, PromptVersion
from app.repositories.generation import GenerationRepository
from app.workflows.generation import workflow_definition


def default_prompt_seed_path() -> Path:
    return Path(__file__).parents[4] / "data" / "prompts" / "sports_short_video_full_package.json"


def load_prompt_seed(path: Path | None = None) -> dict[str, Any]:
    source = path or default_prompt_seed_path()
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported generation seed schema")
    return cast(dict[str, Any], data)


async def seed_generation_defaults(
    session: AsyncSession,
    workspace_id: UUID,
    actor_id: UUID,
    *,
    path: Path | None = None,
) -> dict[str, object]:
    data = load_prompt_seed(path)
    collection_data = cast(dict[str, Any], data["collection"])
    version_data = cast(dict[str, Any], data["version"])
    workflow_data = cast(dict[str, Any], data["workflow"])
    repo = GenerationRepository(session)
    collection = await repo.prompt_collection_by_key(workspace_id, str(collection_data["key"]))
    collection_created = collection is None
    if collection is None:
        collection = PromptCollection(
            id=uuid4(),
            workspace_id=workspace_id,
            key=str(collection_data["key"]),
            name=str(collection_data["name"]),
            description=str(collection_data["description"]),
            category=str(collection_data["category"]),
            current_version_id=None,
            status="active",
            tags=list(collection_data["tags"]),
        )
        session.add(collection)
        await session.flush()
    version = await repo.prompt_version_by_label(
        workspace_id, collection.id, str(version_data["version"])
    )
    version_created = version is None
    if version is None:
        now = datetime.now(UTC)
        version = PromptVersion(
            id=uuid4(),
            workspace_id=workspace_id,
            collection_id=collection.id,
            version=str(version_data["version"]),
            system_prompt=str(version_data["system_prompt"]),
            user_prompt_template=str(version_data["user_prompt_template"]),
            variables_schema=cast(dict[str, Any], version_data["variables_schema"]),
            model_config=cast(dict[str, Any], version_data["model_config"]),
            changelog=str(version_data["changelog"]),
            status="published",
            created_by=actor_id,
            created_at=now,
            published_at=now,
        )
        session.add(version)
        collection.current_version_id = version.id
        await session.flush()
    rule_set = await session.scalar(
        select(RuleSet).where(
            RuleSet.workspace_id == workspace_id,
            RuleSet.key == "elite-sports-narration-v7-9",
        )
    )
    if rule_set is None or rule_set.current_version_id is None:
        raise ValueError("Import and publish the complete V7.9 rule set before seeding generation")
    rule_version = await session.scalar(
        select(RuleSetVersion).where(
            RuleSetVersion.workspace_id == workspace_id,
            RuleSetVersion.id == rule_set.current_version_id,
            RuleSetVersion.status == "published",
        )
    )
    if rule_version is None:
        raise ValueError("The current V7.9 rule version must be published")
    workflow = await repo.workflow_by_key(workspace_id, str(workflow_data["key"]))
    workflow_created = workflow is None
    if workflow is None:
        workflow = GenerationWorkflow(
            id=uuid4(),
            workspace_id=workspace_id,
            key=str(workflow_data["key"]),
            name=str(workflow_data["name"]),
            description=str(workflow_data["description"]),
            input_types=list(workflow_data["input_types"]),
            steps=workflow_definition(),
            default_rule_set_version_id=rule_version.id,
            default_prompt_version_id=version.id,
            enabled=True,
        )
        session.add(workflow)
    else:
        workflow.default_rule_set_version_id = rule_version.id
        workflow.default_prompt_version_id = version.id
    await session.commit()
    return {
        "collection_id": collection.id,
        "prompt_version_id": version.id,
        "workflow_id": workflow.id,
        "collection_created": collection_created,
        "version_created": version_created,
        "workflow_created": workflow_created,
    }
