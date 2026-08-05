from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.config import Settings
from app.models.editorial_rules import Rule, RuleSetVersion
from app.models.generation import (
    GenerationRun,
    GenerationStep,
    GenerationWorkflow,
    PromptCollection,
    PromptVersion,
)
from app.models.monitoring import ContentItem
from app.models.news import Article, EventArticle, Source, TopicEvent
from app.models.operations import SystemEvent
from app.prompts.renderer import PromptRenderError, redact_sensitive, render_prompt
from app.providers.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMProviderAuthenticationError,
    LLMProviderError,
    LLMProviderRateLimitError,
    LLMRequest,
    LLMResponse,
)
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.providers.registry import ProviderRegistry
from app.repositories.generation import GenerationRepository
from app.schemas.generation import (
    GenerationCreate,
    GenerationDecisionUpdate,
    GenerationRunPage,
    GenerationRunRead,
    PromptCollectionCreate,
    PromptCollectionDetail,
    PromptCollectionPage,
    PromptCollectionRead,
    PromptPreviewRead,
    PromptVersionCreate,
    PromptVersionRead,
    PromptVersionSummary,
    PromptVersionUpdate,
    ProviderDescriptor,
    WorkflowRead,
)
from app.services.audit import build_audit_entry, build_external_call_attempt
from app.services.error_detail import business_hint_for
from app.services.settings import SettingsError, SettingsService
from app.workflows.generation import (
    DEFAULT_MAX_CHARS,
    DEFAULT_MIN_CHARS,
    aggregate_usage,
    deterministic_qa,
    extract_claims,
    validate_final_bundle,
)


class GenerationError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class GenerationNotFound(GenerationError):
    def __init__(self, message: str = "生成资源不存在") -> None:
        super().__init__(message, code="generation_not_found", status_code=404)


class GenerationConflict(GenerationError):
    def __init__(self, message: str, code: str = "generation_conflict") -> None:
        super().__init__(message, code=code, status_code=409)


class GenerationService:
    def __init__(
        self,
        session: AsyncSession,
        providers: ProviderRegistry[LLMProvider],
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.providers = providers
        self.repo = GenerationRepository(session)
        self.settings = settings

    async def list_prompts(
        self, workspace_id: UUID, *, page: int, page_size: int
    ) -> PromptCollectionPage:
        items, total = await self.repo.list_prompt_collections(workspace_id, page, page_size)
        reads: list[PromptCollectionRead] = []
        for item in items:
            versions = await self.repo.prompt_versions(workspace_id, item.id)
            reads.append(
                PromptCollectionRead.model_validate(item).model_copy(
                    update={"version_count": len(versions)}
                )
            )
        return PromptCollectionPage(items=reads, page=page, page_size=page_size, total=total)

    async def create_prompt_collection(
        self, workspace_id: UUID, actor_id: UUID, payload: PromptCollectionCreate
    ) -> PromptCollectionRead:
        if await self.repo.prompt_collection_by_key(workspace_id, payload.key):
            raise GenerationConflict("Prompt 集合 key 已存在", "duplicate_prompt_key")
        collection = PromptCollection(
            id=uuid4(),
            workspace_id=workspace_id,
            key=payload.key,
            name=payload.name,
            description=payload.description,
            category=payload.category,
            current_version_id=None,
            status="active",
            tags=payload.tags,
        )
        self.session.add(collection)
        self._audit(
            workspace_id, actor_id, "prompt_collection.created", "prompt_collection", collection.id
        )
        await self.session.commit()
        await self.session.refresh(collection)
        return PromptCollectionRead.model_validate(collection)

    async def prompt_detail(
        self, workspace_id: UUID, collection_id: UUID
    ) -> PromptCollectionDetail:
        collection = await self._collection(workspace_id, collection_id)
        versions = await self.repo.prompt_versions(workspace_id, collection_id)
        base = PromptCollectionRead.model_validate(collection).model_copy(
            update={"version_count": len(versions)}
        )
        return PromptCollectionDetail(
            **base.model_dump(),
            versions=[PromptVersionSummary.model_validate(item) for item in versions],
        )

    async def prompt_version(
        self, workspace_id: UUID, collection_id: UUID, version_id: UUID
    ) -> PromptVersionRead:
        await self._collection(workspace_id, collection_id)
        version = await self._prompt_version(workspace_id, version_id)
        if version.collection_id != collection_id:
            raise GenerationNotFound("Prompt 版本不存在")
        return PromptVersionRead.model_validate(version)

    async def create_prompt_version(
        self,
        workspace_id: UUID,
        collection_id: UUID,
        actor_id: UUID,
        payload: PromptVersionCreate,
    ) -> PromptVersionRead:
        await self._collection(workspace_id, collection_id)
        if await self.repo.prompt_version_by_label(workspace_id, collection_id, payload.version):
            raise GenerationConflict("Prompt 版本号已存在", "duplicate_prompt_version")
        self._validate_prompt_definition(
            payload.system_prompt, payload.user_prompt_template, payload.variables_schema
        )
        version = PromptVersion(
            id=uuid4(),
            workspace_id=workspace_id,
            collection_id=collection_id,
            version=payload.version,
            system_prompt=payload.system_prompt,
            user_prompt_template=payload.user_prompt_template,
            variables_schema=payload.variables_schema,
            model_config=payload.model_config_data,
            changelog=payload.changelog,
            status="draft",
            created_by=actor_id,
            created_at=datetime.now(UTC),
            published_at=None,
        )
        self.session.add(version)
        self._audit(workspace_id, actor_id, "prompt_version.created", "prompt_version", version.id)
        await self.session.commit()
        await self.session.refresh(version)
        return PromptVersionRead.model_validate(version)

    async def update_prompt_version(
        self,
        workspace_id: UUID,
        collection_id: UUID,
        version_id: UUID,
        actor_id: UUID,
        payload: PromptVersionUpdate,
    ) -> PromptVersionRead:
        collection = await self._collection(workspace_id, collection_id)
        version = await self._prompt_version(workspace_id, version_id)
        if version.collection_id != collection.id:
            raise GenerationNotFound("Prompt 版本不存在")
        if version.status == "published":
            next_label = await self._next_prompt_label(workspace_id, collection_id, version.version)
            version = PromptVersion(
                id=uuid4(),
                workspace_id=workspace_id,
                collection_id=collection_id,
                version=next_label,
                system_prompt=version.system_prompt,
                user_prompt_template=version.user_prompt_template,
                variables_schema=dict(version.variables_schema),
                model_config=dict(version.model_config),
                changelog="编辑已发布 Prompt 自动创建草稿",
                status="draft",
                created_by=actor_id,
                created_at=datetime.now(UTC),
                published_at=None,
            )
            self.session.add(version)
        elif version.status != "draft":
            raise GenerationConflict("只有草稿 Prompt 可以编辑", "prompt_not_editable")
        updates = payload.model_dump(exclude_unset=True, by_alias=False)
        for field, value in updates.items():
            attribute = "model_config" if field == "model_config_data" else field
            setattr(version, attribute, value)
        self._validate_prompt_definition(
            version.system_prompt, version.user_prompt_template, version.variables_schema
        )
        self._audit(
            workspace_id,
            actor_id,
            "prompt_version.updated",
            "prompt_version",
            version.id,
            {"fields": sorted(payload.model_fields_set)},
        )
        await self.session.commit()
        await self.session.refresh(version)
        return PromptVersionRead.model_validate(version)

    async def publish_prompt(
        self, workspace_id: UUID, collection_id: UUID, version_id: UUID, actor_id: UUID
    ) -> PromptVersionRead:
        collection = await self._collection(workspace_id, collection_id)
        version = await self._prompt_version(workspace_id, version_id)
        if version.collection_id != collection_id:
            raise GenerationNotFound("Prompt 版本不存在")
        if version.status == "published":
            return PromptVersionRead.model_validate(version)
        if version.status != "draft":
            raise GenerationConflict("只有草稿 Prompt 可以发布", "prompt_not_publishable")
        self._validate_prompt_definition(
            version.system_prompt, version.user_prompt_template, version.variables_schema
        )
        version.status = "published"
        version.published_at = datetime.now(UTC)
        collection.current_version_id = version.id
        self._audit(
            workspace_id, actor_id, "prompt_version.published", "prompt_version", version.id
        )
        await self.session.commit()
        return PromptVersionRead.model_validate(version)

    async def rollback_prompt(
        self, workspace_id: UUID, collection_id: UUID, version_id: UUID, actor_id: UUID
    ) -> PromptVersionRead:
        collection = await self._collection(workspace_id, collection_id)
        version = await self._prompt_version(workspace_id, version_id)
        if version.collection_id != collection_id or version.status != "published":
            raise GenerationConflict("只能回滚到该集合的已发布 Prompt", "prompt_rollback_invalid")
        collection.current_version_id = version.id
        self._audit(
            workspace_id, actor_id, "prompt_version.rolled_back", "prompt_collection", collection.id
        )
        await self.session.commit()
        return PromptVersionRead.model_validate(version)

    async def workflows(self, workspace_id: UUID) -> list[WorkflowRead]:
        return [
            WorkflowRead.model_validate(item) for item in await self.repo.workflows(workspace_id)
        ]

    async def workflow(self, workspace_id: UUID, workflow_id: UUID) -> WorkflowRead:
        workflow = await self._workflow(workspace_id, workflow_id)
        return WorkflowRead.model_validate(workflow)

    async def provider_descriptors(self, workspace_id: UUID) -> list[ProviderDescriptor]:
        descriptors: list[ProviderDescriptor] = []
        for registered in self.providers.values():
            provider = await self._provider(workspace_id, registered.key)
            health = await provider.health_check()
            source: Literal["database", "environment", "builtin", "unconfigured"] = "builtin"
            default_model: str | None = None
            default_parameters: dict[str, Any] = {}
            if provider.key == "openai_compatible" and self.settings is not None:
                setting = await self._settings_service().llm_setting(workspace_id)
                source = setting.source
                default_model = setting.default_model
                default_parameters = setting.default_parameters
            descriptors.append(
                ProviderDescriptor(
                    key=provider.key,
                    name=provider.name,
                    configured=provider.configured,
                    is_mock=provider.is_mock,
                    supports_streaming=provider.supports_streaming,
                    detail=health.detail,
                    source=source,
                    default_model=default_model,
                    default_parameters=default_parameters,
                )
            )
        return descriptors

    async def preview(self, workspace_id: UUID, payload: GenerationCreate) -> PromptPreviewRead:
        workflow, prompt, rule_version = await self._resolve_versions(workspace_id, payload)
        frozen = await self._freeze_input(workspace_id, payload)
        rules, truncated = await self._compile_rules(workspace_id, rule_version.id)
        variables = self._prompt_variables(
            workflow, frozen, rules, payload.model_config_data, "preview"
        )
        try:
            rendered = render_prompt(
                prompt.user_prompt_template, prompt.variables_schema, variables
            )
        except PromptRenderError as exc:
            raise GenerationError(str(exc), code="prompt_render_failed", status_code=422) from exc
        provider = await self._provider(workspace_id, payload.provider)
        warnings = ["预览中的外部输入属于不可信数据，不能覆盖系统指令"]
        if truncated:
            warnings.append("规则包按优先级编译，未将全部规则注入单个步骤")
        return PromptPreviewRead(
            system_prompt=prompt.system_prompt,
            user_prompt=rendered,
            variables=cast(dict[str, Any], redact_sensitive(variables)),
            provider={
                "key": provider.key,
                "configured": provider.configured,
                "is_mock": provider.is_mock,
                "api_key": "***BACKEND ONLY***",
            },
            warnings=warnings,
        )

    async def create_run(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: GenerationCreate,
        idempotency_key: str,
    ) -> tuple[GenerationRunRead, bool]:
        existing = await self.repo.run_by_idempotency(workspace_id, idempotency_key)
        if existing is not None:
            return GenerationRunRead.model_validate(existing), False
        workflow, prompt, rule_version = await self._resolve_versions(workspace_id, payload)
        provider = await self._provider(workspace_id, payload.provider)
        provider_defaults: dict[str, Any] = {}
        input_cost: Decimal | None = None
        output_cost: Decimal | None = None
        if self.settings is not None and provider.key == "openai_compatible":
            (
                _model,
                provider_defaults,
                input_cost,
                output_cost,
            ) = await self._settings_service().effective_llm_defaults(workspace_id)
        merged_config = dict(provider_defaults)
        merged_config.update(prompt.model_config)
        merged_config.update(payload.model_config_data)
        if input_cost is not None:
            merged_config.setdefault("input_cost_per_million", str(input_cost))
        if output_cost is not None:
            merged_config.setdefault("output_cost_per_million", str(output_cost))
        try:
            await provider.validate_config(merged_config)
        except (LLMProviderError, ValueError) as exc:
            raise GenerationError(
                str(exc), code="llm_provider_not_configured", status_code=422
            ) from exc
        frozen = await self._freeze_input(workspace_id, payload)
        input_hash = sha256(
            json.dumps(frozen, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        run = GenerationRun(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=actor_id,
            workflow_id=workflow.id,
            input_type=payload.input_type,
            input_id=payload.input_id,
            input_payload=frozen,
            input_hash=input_hash,
            idempotency_key=idempotency_key,
            rule_set_version_id=rule_version.id,
            prompt_version_id=prompt.id,
            provider=provider.key,
            model=payload.model,
            model_config=merged_config,
            status="queued",
            current_step=None,
            verification_status="verification_incomplete",
            started_at=None,
            completed_at=None,
            raw_output=None,
            final_output=None,
            validation_result={},
            rewrite_count=0,
            token_usage={},
            estimated_cost=None,
            error=None,
            error_code=None,
            error_detail_safe=None,
            error_hint=None,
            run_metadata={
                "source_kind": "live",
                "provider_is_mock": provider.is_mock,
                "workflow_key": workflow.key,
            },
            is_saved=False,
            user_rating=None,
        )
        run.steps = [
            GenerationStep(
                id=uuid4(),
                workspace_id=workspace_id,
                run_id=run.id,
                step_key=str(step["key"]),
                name=str(step["name"]),
                sort_order=int(step["sort_order"]),
                status="pending",
                input_payload={},
                output_payload=None,
                prompt_snapshot=None,
                started_at=None,
                completed_at=None,
                error=None,
            )
            for step in workflow.steps
        ]
        self.session.add(run)
        self._audit(workspace_id, actor_id, "generation_run.created", "generation_run", run.id)
        await self.session.commit()
        loaded = await self._run(workspace_id, run.id)
        return GenerationRunRead.model_validate(loaded), True

    async def list_runs(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        status: str | None,
    ) -> GenerationRunPage:
        items, total = await self.repo.list_runs(
            workspace_id, page=page, page_size=page_size, status=status
        )
        return GenerationRunPage(
            items=[GenerationRunRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_run(self, workspace_id: UUID, run_id: UUID) -> GenerationRunRead:
        return GenerationRunRead.model_validate(await self._run(workspace_id, run_id))

    async def update_decision(
        self,
        workspace_id: UUID,
        run_id: UUID,
        actor_id: UUID,
        payload: GenerationDecisionUpdate,
    ) -> GenerationRunRead:
        run = await self._run(workspace_id, run_id)
        if payload.is_saved is not None:
            run.is_saved = payload.is_saved
        if payload.rating is not None:
            run.user_rating = payload.rating
        self._audit(
            workspace_id, actor_id, "generation_run.decision_updated", "generation_run", run.id
        )
        await self.session.commit()
        return GenerationRunRead.model_validate(await self._run(workspace_id, run.id))

    async def clone_for_manual_rewrite(
        self,
        workspace_id: UUID,
        run_id: UUID,
        actor_id: UUID,
        instruction: str,
    ) -> GenerationRunRead:
        source = await self._run(workspace_id, run_id)
        if source.status != "completed":
            raise GenerationConflict("只能重写已完成的生成运行", "rewrite_source_not_completed")
        workflow = await self._workflow(workspace_id, source.workflow_id)
        clone = GenerationRun(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=actor_id,
            workflow_id=source.workflow_id,
            input_type=source.input_type,
            input_id=source.input_id,
            input_payload=dict(source.input_payload),
            input_hash=source.input_hash,
            idempotency_key=f"manual-rewrite:{source.id}:{uuid4()}",
            rule_set_version_id=source.rule_set_version_id,
            prompt_version_id=source.prompt_version_id,
            provider=source.provider,
            model=source.model,
            model_config=dict(source.model_config),
            status="queued",
            current_step=None,
            verification_status=source.verification_status,
            started_at=None,
            completed_at=None,
            raw_output=None,
            final_output=None,
            validation_result={},
            rewrite_count=0,
            token_usage={},
            estimated_cost=None,
            error=None,
            error_code=None,
            error_detail_safe=None,
            error_hint=None,
            run_metadata={
                "source_kind": source.run_metadata.get("source_kind"),
                "provider_is_mock": source.run_metadata.get("provider_is_mock", False),
                "rewrite_of": str(source.id),
                "manual_rewrite_instruction": instruction,
            },
            is_saved=False,
            user_rating=None,
        )
        clone.steps = [
            GenerationStep(
                id=uuid4(),
                workspace_id=workspace_id,
                run_id=clone.id,
                step_key=str(step["key"]),
                name=str(step["name"]),
                sort_order=int(step["sort_order"]),
                status="pending",
                input_payload={},
                output_payload=None,
                prompt_snapshot=None,
                started_at=None,
                completed_at=None,
                error=None,
            )
            for step in workflow.steps
        ]
        self.session.add(clone)
        self._audit(
            workspace_id, actor_id, "generation_run.manual_rewrite", "generation_run", clone.id
        )
        await self.session.commit()
        return GenerationRunRead.model_validate(await self._run(workspace_id, clone.id))

    async def queue_retry(
        self, workspace_id: UUID, run_id: UUID, actor_id: UUID
    ) -> GenerationRunRead:
        run = await self._run(workspace_id, run_id)
        if run.status not in {"failed", "cancelled"}:
            raise GenerationConflict("只有失败或取消的运行可以重试", "generation_not_retryable")
        run.status = "queued"
        run.current_step = None
        run.error = None
        run.error_code = None
        run.error_detail_safe = None
        run.error_hint = None
        run.completed_at = None
        self._audit(workspace_id, actor_id, "generation_run.retried", "generation_run", run.id)
        await self.session.commit()
        return GenerationRunRead.model_validate(await self._run(workspace_id, run.id))

    async def mark_dispatch_failure(self, workspace_id: UUID, run_id: UUID) -> None:
        run = await self._run(workspace_id, run_id)
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        run.error = {
            "code": "generation_dispatch_failed",
            "message": "Background generation worker is unavailable",
        }
        run.error_code = "generation_dispatch_failed"
        run.error_detail_safe = "Background generation worker is unavailable"
        run.error_hint = business_hint_for("generation_dispatch_failed", category="generation")
        await self.session.commit()

    async def execute_run(self, run_id: UUID) -> None:
        run = cast(
            GenerationRun | None,
            await self.session.scalar(
                select(GenerationRun)
                .options(selectinload(GenerationRun.steps))
                .where(GenerationRun.id == run_id)
                .with_for_update()
            ),
        )
        if run is None:
            raise GenerationNotFound("生成运行不存在")
        if run.status == "completed":
            return
        if run.status == "running":
            raise GenerationConflict("生成运行正在执行", "generation_already_running")
        provider = await self._provider(run.workspace_id, run.provider)
        prompt = await self._prompt_version(run.workspace_id, run.prompt_version_id)
        workflow = await self._workflow(run.workspace_id, run.workflow_id)
        rule_version = cast(
            RuleSetVersion | None,
            await self.session.scalar(
                select(RuleSetVersion).where(
                    RuleSetVersion.workspace_id == run.workspace_id,
                    RuleSetVersion.id == run.rule_set_version_id,
                )
            ),
        )
        if rule_version is None:
            raise GenerationNotFound("固定的规则版本不存在")
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.error = None
        run.error_code = None
        run.error_detail_safe = None
        run.error_hint = None
        await self.session.commit()

        context: dict[str, Any] = {"frozen_input": run.input_payload}
        usage_records: list[dict[str, Any]] = []
        cost_total = Decimal("0")
        try:
            for step in sorted(run.steps, key=lambda item: item.sort_order):
                run.current_step = step.step_key
                step.status = "running"
                step.started_at = datetime.now(UTC)
                step.input_payload = self._step_input(step.step_key, context)
                await self.session.commit()
                output, response = await self._execute_step(
                    run, workflow, prompt, rule_version, provider, step.step_key, context
                )
                if response is not None:
                    usage = {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "total_tokens": response.usage.total_tokens,
                        "source": response.usage.source,
                    }
                    usage_records.append(usage)
                    estimated = await provider.estimate_cost(response.usage, run.model_config)
                    if estimated is not None:
                        cost_total += estimated
                context[step.step_key] = output
                step.output_payload = output
                step.status = "completed"
                step.completed_at = datetime.now(UTC)
                await self.session.commit()
            run.status = "completed"
            run.current_step = None
            run.completed_at = datetime.now(UTC)
            run.token_usage = aggregate_usage(usage_records)
            run.estimated_cost = cost_total
            run.raw_output = {
                "draft": context.get("generate_draft"),
                "provider": run.provider,
                "model": run.model,
                "mock": provider.is_mock,
            }
            run.final_output = cast(dict[str, Any], context.get("final_formatting"))
            run.validation_result = cast(dict[str, Any], context.get("qa_validation", {}))
            self.session.add(
                SystemEvent(
                    id=uuid4(),
                    workspace_id=run.workspace_id,
                    severity="info",
                    category="generation",
                    event_type="generation.completed",
                    message="内容生成工作流已完成",
                    resource_type="generation_run",
                    resource_id=run.id,
                    status="resolved",
                    metadata_safe_json={
                        "provider": run.provider,
                        "model": run.model,
                        "mock": provider.is_mock,
                    },
                    trace_id=uuid4(),
                    created_at=datetime.now(UTC),
                )
            )
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            failed = cast(
                GenerationRun | None,
                await self.session.scalar(
                    select(GenerationRun)
                    .options(selectinload(GenerationRun.steps))
                    .where(GenerationRun.id == run_id)
                ),
            )
            if failed is not None:
                failed.status = "failed"
                failed.completed_at = datetime.now(UTC)
                code = getattr(exc, "code", "generation_execution_failed")
                failed.error = {
                    "code": code,
                    "message": str(exc)[:1000],
                }
                failed.error_code = code
                failed.error_detail_safe = str(exc)[:2000]
                failed.error_hint = business_hint_for(code, category="generation")
                current = next(
                    (item for item in failed.steps if item.step_key == failed.current_step), None
                )
                if current is not None:
                    current.status = "failed"
                    current.completed_at = datetime.now(UTC)
                    current.error = dict(failed.error)
                self.session.add(
                    SystemEvent(
                        id=uuid4(),
                        workspace_id=failed.workspace_id,
                        severity="error",
                        category="generation",
                        event_type="generation.run_failed",
                        message=f"生成工作流执行失败：{str(exc)[:200]}",
                        resource_type="generation_run",
                        resource_id=failed.id,
                        status="open",
                        error_code=code,
                        error_detail=str(exc)[:2000],
                        error_hint=business_hint_for(code, category="generation"),
                        metadata_safe_json={"model": failed.model, "provider": failed.provider},
                        trace_id=uuid4(),
                        created_at=datetime.now(UTC),
                    )
                )
                await self.session.commit()
            raise

    async def _execute_step(
        self,
        run: GenerationRun,
        workflow: GenerationWorkflow,
        prompt: PromptVersion,
        rule_version: RuleSetVersion,
        provider: LLMProvider,
        step_key: str,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], LLMResponse | None]:
        frozen = cast(dict[str, Any], context["frozen_input"])
        if step_key == "research_input":
            sources = cast(list[dict[str, Any]], frozen.get("sources", []))
            status = (
                "corroborated"
                if len({item.get("source_id") for item in sources}) >= 2
                else "verification_incomplete"
            )
            run.verification_status = status
            return {
                "sources": sources,
                "verification_status": status,
                "note": "No LLM claim of web access; evidence comes only from frozen system input",
            }, None
        if step_key == "normalize_facts":
            claims = extract_claims(frozen)
            evidence_ids = [
                str(item.get("source_id")) for item in context["research_input"]["sources"]
            ]
            return {
                "facts": [
                    {
                        "id": f"fact-{index}",
                        "statement": statement,
                        "evidence_ids": evidence_ids,
                        "verification_status": run.verification_status,
                    }
                    for index, statement in enumerate(claims, start=1)
                ]
            }, None
        if step_key == "build_timeline":
            event_time = frozen.get("event_time") or frozen.get("published_at")
            return {
                "timeline": [
                    {
                        "event_time": event_time,
                        "statement": fact["statement"],
                        "time_basis": "event_time"
                        if frozen.get("event_time")
                        else "published_at_or_unknown",
                    }
                    for fact in context["normalize_facts"]["facts"]
                ]
            }, None
        if step_key == "story_qualification":
            facts = context["normalize_facts"]["facts"]
            score = int(float(frozen.get("story_score") or 50)) if facts else 0
            return {
                "qualified": bool(facts),
                "score": max(0, min(100, score)),
                "reason": "存在可追溯输入事实" if facts else "输入中没有可用事实",
                "editorial_judgement": True,
            }, None
        if step_key == "apply_rules":
            rules, truncated = await self._compile_rules(run.workspace_id, rule_version.id)
            return {
                "rule_set_version_id": str(rule_version.id),
                "rules": rules,
                "truncated_for_context": truncated,
            }, None
        if step_key == "generate_draft":
            response, snapshot = await self._call_provider(
                run, workflow, prompt, provider, step_key, context, response_schema=None
            )
            if not isinstance(response.content, str):
                raise GenerationError(
                    "Draft provider response must be text", code="draft_contract_error"
                )
            self._set_prompt_snapshot(run, step_key, snapshot)
            return {"tts_en": response.content}, response
        if step_key == "editorial_review":
            draft = str(context["generate_draft"]["tts_en"])
            findings: list[dict[str, Any]] = []
            if not draft.strip():
                findings.append({"code": "empty_draft", "severity": "error"})
            return {"passed": not findings, "findings": findings}, None
        if step_key == "qa_validation":
            config = run.model_config
            answer_words, answer_ratio = self._answer_protection(frozen)
            return deterministic_qa(
                str(context["generate_draft"]["tts_en"]),
                target_min_chars=int(config.get("target_min_chars", DEFAULT_MIN_CHARS)),
                target_max_chars=int(config.get("target_max_chars", DEFAULT_MAX_CHARS)),
                verification_status=run.verification_status,
                protected_answer_words=answer_words,
                answer_reveal_min_ratio=answer_ratio,
            ), None
        if step_key == "automatic_rewrite":
            qa = cast(dict[str, Any], context["qa_validation"])
            draft = str(context["generate_draft"]["tts_en"])
            responses: list[dict[str, Any]] = []
            last_response: LLMResponse | None = None
            max_rewrites = int(run.model_config.get("max_rewrites", 2))
            answer_words, answer_ratio = self._answer_protection(frozen)
            manual_instruction = run.run_metadata.get("manual_rewrite_instruction")
            must_rewrite = bool(qa.get("errors")) or bool(manual_instruction)
            while must_rewrite and run.rewrite_count < max_rewrites:
                response, snapshot = await self._call_provider(
                    run,
                    workflow,
                    prompt,
                    provider,
                    step_key,
                    {**context, "rewrite_draft": draft, "rewrite_qa": qa},
                    response_schema=None,
                )
                if not isinstance(response.content, str):
                    raise GenerationError(
                        "Rewrite provider response must be text", code="rewrite_contract_error"
                    )
                last_response = response
                draft = response.content
                run.rewrite_count += 1
                qa = deterministic_qa(
                    draft,
                    target_min_chars=int(
                        run.model_config.get("target_min_chars", DEFAULT_MIN_CHARS)
                    ),
                    target_max_chars=int(
                        run.model_config.get("target_max_chars", DEFAULT_MAX_CHARS)
                    ),
                    verification_status=run.verification_status,
                    protected_answer_words=answer_words,
                    answer_reveal_min_ratio=answer_ratio,
                )
                responses.append({"attempt": run.rewrite_count, "qa": qa})
                self._set_prompt_snapshot(run, step_key, snapshot)
                must_rewrite = bool(qa.get("errors"))
            if qa.get("errors"):
                raise GenerationError(
                    "Automatic rewrite limit reached before QA passed",
                    code="qa_rewrite_limit_reached",
                )
            context["generate_draft"] = {"tts_en": draft}
            context["qa_validation"] = qa
            return {
                "rewritten": bool(responses),
                "rewrite_count": run.rewrite_count,
                "attempts": responses,
                "final_tts_en": draft,
            }, last_response
        if step_key == "final_formatting":
            response, snapshot = await self._call_provider(
                run,
                workflow,
                prompt,
                provider,
                step_key,
                context,
                response_schema={"type": "object"},
            )
            if not isinstance(response.content, dict):
                content = dict(response.content) if not isinstance(response.content, str) else None
                if content is None:
                    raise GenerationError(
                        "Final provider response must be an object", code="final_contract_error"
                    )
            else:
                content = dict(response.content)

            # ── 后端强制覆盖字段（不允许 LLM 覆盖事实或审计字段） ──────────────
            # tts_en 必须来自 generate_draft / automatic_rewrite 的输出，
            # 而不是 final_formatting 步骤 LLM 的重新生成版本。
            content["tts_en"] = str(context["generate_draft"]["tts_en"])
            content["fact_sources"] = context["research_input"]["sources"]
            content["qa_report"] = context["qa_validation"]
            content["used_rules"] = [item["key"] for item in context["apply_rules"]["rules"]]
            content["rewrite_reasons"] = [
                item.get("code") for item in context["qa_validation"].get("findings", [])
            ]

            # ── 后端计算字段（不依赖 LLM，确保与 tts_en 严格一致） ─────────────
            # spoken_char_count：不含标题/标签/XML/TTS标签/中文翻译的精确字符数
            content["spoken_char_count"] = len(content["tts_en"])

            # verification_status：从 run 对象复制，不允许 LLM 改写核实级别
            content["verification_status"] = run.verification_status

            # ── B 组可选字段默认值（LLM 未生成时给出明确空值，不静默缺失） ──────
            # lcr_enabled：LCR 是否满足启用条件，必须是布尔值
            if "lcr_enabled" not in content:
                content["lcr_enabled"] = False
            elif not isinstance(content.get("lcr_enabled"), bool):
                # 容错：LLM 有时返回字符串 "true"/"false"
                raw_lcr = content["lcr_enabled"]
                content["lcr_enabled"] = str(raw_lcr).lower() in ("true", "1", "yes")

            # C 组 ambiguous 可选字段：允许 null，不强制要求（原文不完整）
            for optional_field in (
                "lcr_reason",
                "hook_candidates",
                "story_format_reason",
                "clean_source_script",
                "source_translation",
                "answer_word_map",
                "reaction_relay",
                "evidence_rewards",
                "exclusion_ladder",
                "dialogue_notes",
                "audio_performance_map",
                "tts_settings",
                "video_material_plan",
                "edit_map",
                "caption_map",
                "original_audio_plan",
                "srt_output",
            ):
                content.setdefault(optional_field, None)

            errors = validate_final_bundle(content)
            if errors:
                raise GenerationError("; ".join(errors), code="final_output_invalid")
            self._set_prompt_snapshot(run, step_key, snapshot)
            return content, response
        raise GenerationError(
            f"Unsupported workflow step: {step_key}", code="workflow_step_unsupported"
        )

    async def _call_provider(
        self,
        run: GenerationRun,
        workflow: GenerationWorkflow,
        prompt: PromptVersion,
        provider: LLMProvider,
        step_key: str,
        context: dict[str, Any],
        *,
        response_schema: dict[str, Any] | None,
    ) -> tuple[LLMResponse, dict[str, Any]]:
        rules = cast(list[dict[str, Any]], context.get("apply_rules", {}).get("rules", []))
        variables = self._prompt_variables(
            workflow, run.input_payload, rules, run.model_config, step_key, context
        )
        try:
            user_prompt = render_prompt(
                prompt.user_prompt_template, prompt.variables_schema, variables
            )
        except PromptRenderError as exc:
            raise GenerationError(str(exc), code="prompt_render_failed") from exc
        snapshot = {
            "prompt_version_id": str(prompt.id),
            "system_prompt": prompt.system_prompt,
            "user_prompt": user_prompt,
            "variables": redact_sensitive(variables),
        }
        request = LLMRequest(
            model=run.model,
            messages=(
                LLMMessage(role="system", content=prompt.system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ),
            parameters=run.model_config,
            response_schema=response_schema,
            timeout_seconds=float(run.model_config.get("timeout_seconds", 60)),
            idempotency_key=f"{run.id}:{step_key}:{run.rewrite_count}",
            metadata={
                "step_key": step_key,
                "title": run.input_payload.get("title"),
                "sources": run.input_payload.get("sources", []),
                "used_rules": [item["key"] for item in rules],
                "rewrite_reasons": [
                    item.get("code")
                    for item in cast(dict[str, Any], context.get("qa_validation", {})).get(
                        "findings", []
                    )
                ],
            },
        )
        started_at = datetime.now(UTC)
        attempt_number = run.rewrite_count + 1
        try:
            response = await provider.generate(request)
            finished_at = datetime.now(UTC)
            self.session.add(
                build_external_call_attempt(
                    id=uuid4(),
                    workspace_id=run.workspace_id,
                    call_type="llm",
                    provider_key=provider.key,
                    entity_type="generation_run",
                    entity_id=run.id,
                    attempt_number=attempt_number,
                    status="success",
                    target_url=None,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
                    http_status=None,
                    error_code=None,
                    error_detail_safe=None,
                    retryable=None,
                    request_summary={"step_key": step_key, "model": run.model},
                    response_summary={
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "total_tokens": response.usage.total_tokens,
                        "usage_source": response.usage.source,
                    },
                )
            )
            return response, snapshot
        except (LLMProviderRateLimitError, LLMProviderAuthenticationError) as exc:
            finished_at = datetime.now(UTC)
            self.session.add(
                build_external_call_attempt(
                    id=uuid4(),
                    workspace_id=run.workspace_id,
                    call_type="llm",
                    provider_key=provider.key,
                    entity_type="generation_run",
                    entity_id=run.id,
                    attempt_number=attempt_number,
                    status="failed",
                    target_url=None,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
                    http_status=None,
                    error_code=exc.code,
                    error_detail_safe=str(exc)[:500],
                    retryable=exc.retryable,
                    request_summary={"step_key": step_key, "model": run.model},
                    response_summary=None,
                )
            )
            # ── Fallback: retry via llm_fallback_base_url if configured ──────
            fallback_url = self.settings.llm_fallback_base_url if self.settings else None
            if fallback_url:
                fallback_response = await self._attempt_fallback(
                    run, request, step_key, fallback_url, attempt_number
                )
                if fallback_response is not None:
                    return fallback_response, snapshot
            raise GenerationError(str(exc), code=exc.code, status_code=502) from exc
        except LLMProviderError as exc:
            finished_at = datetime.now(UTC)
            self.session.add(
                build_external_call_attempt(
                    id=uuid4(),
                    workspace_id=run.workspace_id,
                    call_type="llm",
                    provider_key=provider.key,
                    entity_type="generation_run",
                    entity_id=run.id,
                    attempt_number=attempt_number,
                    status="failed",
                    target_url=None,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
                    http_status=None,
                    error_code=exc.code,
                    error_detail_safe=str(exc)[:500],
                    retryable=exc.retryable,
                    request_summary={"step_key": step_key, "model": run.model},
                    response_summary=None,
                )
            )
            raise GenerationError(str(exc), code=exc.code, status_code=502) from exc
        except Exception:
            finished_at = datetime.now(UTC)
            self.session.add(
                build_external_call_attempt(
                    id=uuid4(),
                    workspace_id=run.workspace_id,
                    call_type="llm",
                    provider_key=provider.key,
                    entity_type="generation_run",
                    entity_id=run.id,
                    attempt_number=attempt_number,
                    status="failed",
                    target_url=None,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
                    http_status=None,
                    error_code="unexpected_llm_provider_error",
                    error_detail_safe="LLM provider failed unexpectedly",
                    retryable=False,
                    request_summary={"step_key": step_key, "model": run.model},
                    response_summary=None,
                )
            )
            raise

    async def _attempt_fallback(
        self,
        run: GenerationRun,
        request: LLMRequest,
        step_key: str,
        fallback_url: str,
        attempt_number: int,
    ) -> LLMResponse | None:
        """Retry a failed LLM request via the configured fallback endpoint.

        Returns the response on success, or None if the fallback also fails.
        """
        import logging as _logging

        _logger = _logging.getLogger(__name__)
        internal_hosts = tuple(self.settings.llm_internal_hosts_allowlist if self.settings else [])
        fallback_provider = OpenAICompatibleProvider(
            base_url=fallback_url,
            api_key="fallback-no-key-required",
            timeout_seconds=float(request.parameters.get("timeout_seconds", 60)),
            max_attempts=1,
            internal_hosts=internal_hosts,
        )
        fallback_started = datetime.now(UTC)
        try:
            response = await fallback_provider.generate(request)
            fallback_finished = datetime.now(UTC)
            self.session.add(
                build_external_call_attempt(
                    id=uuid4(),
                    workspace_id=run.workspace_id,
                    call_type="llm",
                    provider_key="llm_fallback",
                    entity_type="generation_run",
                    entity_id=run.id,
                    attempt_number=attempt_number,
                    status="success",
                    target_url=fallback_url,
                    started_at=fallback_started,
                    finished_at=fallback_finished,
                    duration_ms=max(
                        0,
                        int((fallback_finished - fallback_started).total_seconds() * 1000),
                    ),
                    http_status=None,
                    error_code=None,
                    error_detail_safe=None,
                    retryable=None,
                    request_summary={
                        "step_key": step_key,
                        "model": run.model,
                        "fallback": True,
                    },
                    response_summary={
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "total_tokens": response.usage.total_tokens,
                        "usage_source": response.usage.source,
                    },
                )
            )
            _logger.info(
                "LLM fallback succeeded",
                extra={
                    "event": "llm.fallback.success",
                    "fallback_url": fallback_url,
                    "step_key": step_key,
                },
            )
            return response
        except Exception as fallback_exc:
            fallback_finished = datetime.now(UTC)
            self.session.add(
                build_external_call_attempt(
                    id=uuid4(),
                    workspace_id=run.workspace_id,
                    call_type="llm",
                    provider_key="llm_fallback",
                    entity_type="generation_run",
                    entity_id=run.id,
                    attempt_number=attempt_number,
                    status="failed",
                    target_url=fallback_url,
                    started_at=fallback_started,
                    finished_at=fallback_finished,
                    duration_ms=max(
                        0,
                        int((fallback_finished - fallback_started).total_seconds() * 1000),
                    ),
                    http_status=None,
                    error_code="llm_fallback_failed",
                    error_detail_safe=str(fallback_exc)[:500],
                    retryable=False,
                    request_summary={
                        "step_key": step_key,
                        "model": run.model,
                        "fallback": True,
                    },
                    response_summary=None,
                )
            )
            _logger.warning(
                "LLM fallback also failed",
                extra={
                    "event": "llm.fallback.failed",
                    "fallback_url": fallback_url,
                    "error": str(fallback_exc)[:200],
                },
            )
            return None

    def _set_prompt_snapshot(
        self, run: GenerationRun, step_key: str, snapshot: dict[str, Any]
    ) -> None:
        step = next(item for item in run.steps if item.step_key == step_key)
        step.prompt_snapshot = snapshot

    async def _resolve_versions(
        self, workspace_id: UUID, payload: GenerationCreate
    ) -> tuple[GenerationWorkflow, PromptVersion, RuleSetVersion]:
        workflow = await self._workflow(workspace_id, payload.workflow_id)
        if not workflow.enabled:
            raise GenerationConflict("工作流已停用", "workflow_disabled")
        if payload.input_type not in workflow.input_types:
            raise GenerationError(
                "工作流不支持该输入类型", code="workflow_input_not_supported", status_code=422
            )
        prompt_id = payload.prompt_version_id or workflow.default_prompt_version_id
        rule_id = payload.rule_set_version_id or workflow.default_rule_set_version_id
        if prompt_id is None or rule_id is None:
            raise GenerationConflict(
                "工作流缺少已发布的默认 Prompt 或 7.9 规则版本",
                "workflow_defaults_incomplete",
            )
        prompt = await self._prompt_version(workspace_id, prompt_id)
        if prompt.status != "published":
            raise GenerationConflict("生成只能使用已发布 Prompt", "prompt_version_not_published")
        rule_version = cast(
            RuleSetVersion | None,
            await self.session.scalar(
                select(RuleSetVersion).where(
                    RuleSetVersion.workspace_id == workspace_id,
                    RuleSetVersion.id == rule_id,
                    RuleSetVersion.status == "published",
                )
            ),
        )
        if rule_version is None:
            raise GenerationConflict("生成只能使用已发布规则版本", "rule_version_not_published")
        return workflow, prompt, rule_version

    async def _freeze_input(self, workspace_id: UUID, payload: GenerationCreate) -> dict[str, Any]:
        creator_controls = self._creator_controls(payload.input_payload)
        if payload.input_type == "user_text":
            return {
                "text": str(payload.input_payload["text"]).strip(),
                "title": str(payload.input_payload.get("title") or "用户输入事件"),
                "language": payload.input_payload.get("language"),
                "source_kind": "imported",
                "sources": [],
                "frozen_at": datetime.now(UTC).isoformat(),
                "verification_status": "verification_incomplete",
                **creator_controls,
            }
        if payload.input_type == "news":
            article = cast(
                Article | None,
                await self.session.scalar(
                    select(Article)
                    .options(joinedload(Article.source))
                    .where(Article.workspace_id == workspace_id, Article.id == payload.input_id)
                ),
            )
            if article is None:
                raise GenerationNotFound("新闻输入不存在")
            return {**self._article_payload(article, article.source), **creator_controls}
        if payload.input_type == "event":
            event = cast(
                TopicEvent | None,
                await self.session.scalar(
                    select(TopicEvent).where(
                        TopicEvent.workspace_id == workspace_id, TopicEvent.id == payload.input_id
                    )
                ),
            )
            if event is None:
                raise GenerationNotFound("事件输入不存在")
            rows = (
                await self.session.execute(
                    select(Article, Source)
                    .join(EventArticle, EventArticle.article_id == Article.id)
                    .join(Source, Source.id == Article.source_id)
                    .where(EventArticle.event_id == event.id, Article.workspace_id == workspace_id)
                    .order_by(Article.published_at)
                )
            ).all()
            return {
                "title": event.title,
                "summary": event.summary,
                "event_time": event.start_time.isoformat() if event.start_time else None,
                "sport": event.sport,
                "league": event.league,
                "heat_score": float(event.heat_score),
                "story_score": float(event.story_score),
                "source_kind": "live" if rows else "imported",
                "sources": [self._source_payload(article, source) for article, source in rows],
                "articles": [
                    {"title": article.title, "summary": article.summary} for article, _ in rows
                ],
                "frozen_at": datetime.now(UTC).isoformat(),
                **creator_controls,
            }
        content = cast(
            ContentItem | None,
            await self.session.scalar(
                select(ContentItem).where(
                    ContentItem.workspace_id == workspace_id, ContentItem.id == payload.input_id
                )
            ),
        )
        if content is None:
            raise GenerationNotFound("作品输入不存在")
        return {
            "title": content.title,
            "description": content.description,
            "published_at": content.published_at.isoformat() if content.published_at else None,
            "language": content.language,
            "source_kind": content.source_kind,
            "sources": [
                {
                    "source_id": str(content.id),
                    "provider": content.source_provider,
                    "source_kind": content.source_kind,
                    "url": content.canonical_url,
                    "fetched_at": content.fetched_at.isoformat(),
                }
            ],
            "frozen_at": datetime.now(UTC).isoformat(),
            **creator_controls,
        }

    @staticmethod
    def _creator_controls(payload: dict[str, Any]) -> dict[str, Any]:
        """Copy only bounded creator controls; source facts remain database-owned."""
        controls: dict[str, Any] = {}
        answer_word = payload.get("answer_word")
        if isinstance(answer_word, str) and answer_word.strip():
            controls["answer_word"] = answer_word.strip()[:200]
            raw_ratio = payload.get("answer_reveal_min_ratio", 0.55)
            try:
                ratio = float(raw_ratio)
            except (TypeError, ValueError):
                ratio = 0.55
            controls["answer_reveal_min_ratio"] = max(0.25, min(0.9, ratio))
        creator_brief = payload.get("creator_brief")
        if isinstance(creator_brief, str) and creator_brief.strip():
            controls["creator_brief"] = creator_brief.strip()[:2000]
        return controls

    def _article_payload(self, article: Article, source: Source) -> dict[str, Any]:
        return {
            "title": article.title,
            "summary": article.summary,
            "content": article.content,
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "event_time": article.event_time.isoformat() if article.event_time else None,
            "language": article.language,
            "sport": article.sport,
            "league": article.league,
            "source_kind": article.source_kind,
            "sources": [self._source_payload(article, source)],
            "frozen_at": datetime.now(UTC).isoformat(),
        }

    def _source_payload(self, article: Article, source: Source) -> dict[str, Any]:
        return {
            "source_id": str(source.id),
            "article_id": str(article.id),
            "name": source.name,
            "provider": article.source_provider,
            "source_kind": article.source_kind,
            "url": article.canonical_url,
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "fetched_at": article.fetched_at.isoformat(),
            "reliability_score": float(source.reliability_score),
        }

    async def _compile_rules(
        self, workspace_id: UUID, version_id: UUID
    ) -> tuple[list[dict[str, Any]], bool]:
        rules = list(
            (
                await self.session.scalars(
                    select(Rule)
                    .where(
                        Rule.workspace_id == workspace_id,
                        Rule.version_id == version_id,
                        Rule.enabled.is_(True),
                    )
                    .order_by(Rule.is_mandatory.desc(), Rule.priority.desc(), Rule.sort_order)
                )
            ).all()
        )
        mandatory = [item for item in rules if item.is_mandatory]
        optional = [item for item in rules if not item.is_mandatory]
        selected = mandatory + optional[: max(0, 120 - len(mandatory))]
        return [
            {
                "id": str(item.id),
                "key": item.key,
                "title": item.title,
                "instruction": item.instruction,
                "priority": item.priority,
                "mandatory": item.is_mandatory,
                "qa_check": item.qa_check,
                "rewrite_instruction": item.rewrite_instruction,
            }
            for item in selected
        ], len(selected) < len(rules)

    def _prompt_variables(
        self,
        workflow: GenerationWorkflow,
        frozen: dict[str, Any],
        rules: list[dict[str, Any]],
        model_config: dict[str, Any],
        step_key: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "workflow_name": workflow.name,
            "step_name": step_key,
            "input_data": frozen,
            "facts": (context or {}).get("normalize_facts", {}).get("facts", []),
            "timeline": (context or {}).get("build_timeline", {}).get("timeline", []),
            "qualification": (context or {}).get("story_qualification", {}),
            "editorial_rules": rules,
            "current_draft": (context or {}).get("rewrite_draft")
            or (context or {}).get("generate_draft", {}).get("tts_en", ""),
            "qa_findings": (context or {}).get("rewrite_qa", {}).get("findings", []),
            "manual_rewrite_instruction": (context or {}).get("manual_rewrite_instruction", ""),
            "target_min_chars": int(model_config.get("target_min_chars", DEFAULT_MIN_CHARS)),
            "target_max_chars": int(model_config.get("target_max_chars", DEFAULT_MAX_CHARS)),
            "verification_status": frozen.get("verification_status", "verification_incomplete"),
        }

    def _step_input(self, step_key: str, context: dict[str, Any]) -> dict[str, Any]:
        if step_key == "research_input":
            return {"frozen_input": context["frozen_input"]}
        return {key: value for key, value in context.items() if key != "frozen_input"}

    @staticmethod
    def _answer_protection(frozen: dict[str, Any]) -> tuple[list[str], float]:
        configured = frozen.get("protected_answer_words")
        words = [str(item) for item in configured] if isinstance(configured, list) else []
        single = frozen.get("answer_word")
        if isinstance(single, str) and single.strip():
            words.append(single)
        try:
            ratio = float(frozen.get("answer_reveal_min_ratio", 0.55))
        except (TypeError, ValueError):
            ratio = 0.55
        return list(dict.fromkeys(item.strip() for item in words if item.strip())), ratio

    def _validate_prompt_definition(
        self, system_prompt: str, user_prompt: str, schema: dict[str, Any]
    ) -> None:
        if not system_prompt.strip() or not user_prompt.strip():
            raise GenerationError(
                "Prompt 正文不能为空", code="prompt_definition_invalid", status_code=422
            )
        if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
            raise GenerationError(
                "variables_schema 必须是具有 properties 的 object schema",
                code="prompt_schema_invalid",
                status_code=422,
            )
        # Rendering a full run needs runtime values, but this validates placeholder names.
        allowed = set(schema["properties"])
        from app.prompts.renderer import PLACEHOLDER

        referenced = set(PLACEHOLDER.findall(user_prompt))
        unknown = {item.split(".", maxsplit=1)[0] for item in referenced} - allowed
        if unknown:
            raise GenerationError(
                f"Prompt 引用了 schema 未声明的变量：{', '.join(sorted(unknown))}",
                code="prompt_schema_invalid",
                status_code=422,
            )

    async def _provider(self, workspace_id: UUID, key: str) -> LLMProvider:
        if self.settings is not None:
            try:
                return await self._settings_service().resolve_llm_provider(workspace_id, key)
            except SettingsError as exc:
                raise GenerationError(str(exc), code=exc.code, status_code=exc.status_code) from exc
        try:
            return self.providers.get(key)
        except LookupError as exc:
            raise GenerationError(
                "未知 LLM Provider", code="llm_provider_unknown", status_code=422
            ) from exc

    def _settings_service(self) -> SettingsService:
        if self.settings is None:
            raise RuntimeError("runtime settings are unavailable")
        return SettingsService(self.session, self.settings, self.providers)

    async def _collection(self, workspace_id: UUID, collection_id: UUID) -> PromptCollection:
        item = await self.repo.prompt_collection(workspace_id, collection_id)
        if item is None:
            raise GenerationNotFound("Prompt 集合不存在")
        return item

    async def _prompt_version(self, workspace_id: UUID, version_id: UUID) -> PromptVersion:
        item = await self.repo.prompt_version(workspace_id, version_id)
        if item is None:
            raise GenerationNotFound("Prompt 版本不存在")
        return item

    async def _workflow(self, workspace_id: UUID, workflow_id: UUID) -> GenerationWorkflow:
        item = await self.repo.workflow(workspace_id, workflow_id)
        if item is None:
            raise GenerationNotFound("生成工作流不存在")
        return item

    async def _run(self, workspace_id: UUID, run_id: UUID) -> GenerationRun:
        item = await self.repo.run(workspace_id, run_id)
        if item is None:
            raise GenerationNotFound("生成运行不存在")
        return item

    async def _next_prompt_label(self, workspace_id: UUID, collection_id: UUID, base: str) -> str:
        clean = base.split("-draft.", maxsplit=1)[0]
        index = 1
        while await self.repo.prompt_version_by_label(
            workspace_id, collection_id, f"{clean}-draft.{index}"
        ):
            index += 1
        return f"{clean}-draft.{index}"

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        changes: dict[str, Any] | None = None,
        *,
        status: str = "success",
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                before_hash=None,
                after_hash=None,
                change_summary_json=changes or {},
                reason=None,
                ip_hash=None,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
                status=status,
                error_code=error_code,
                error_detail=error_detail,
            )
        )


def enqueue_generation(run_id: UUID) -> None:
    from app.tasks.generation import execute_generation

    execute_generation.delay(str(run_id))
