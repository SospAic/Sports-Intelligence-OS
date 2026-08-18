"""CRUD and descriptive reporting for content experiments."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.experiments import ContentExperiment, ContentExperimentVariant
from app.models.monitoring import ContentItem
from app.models.publication import PerformanceAttribution, Publication
from app.schemas.experiments import (
    ExperimentCreate,
    ExperimentDetail,
    ExperimentPage,
    ExperimentRead,
    ExperimentReport,
    ExperimentReportVariant,
    ExperimentSourceKind,
    ExperimentUpdate,
    ExperimentVariantCreate,
    ExperimentVariantRead,
    ExperimentWindowKey,
)
from app.services.audit import build_audit_entry


class ExperimentError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ExperimentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_experiments(
        self, workspace_id: UUID, *, page: int, page_size: int
    ) -> ExperimentPage:
        conditions = [ContentExperiment.workspace_id == workspace_id]
        rows = list(
            (
                await self.session.scalars(
                    select(ContentExperiment)
                    .where(*conditions)
                    .order_by(ContentExperiment.updated_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ContentExperiment).where(*conditions)
            )
            or 0
        )
        counts = await self._variant_counts(workspace_id, [item.id for item in rows])
        return ExperimentPage(
            items=[self._read(item, counts.get(item.id, 0)) for item in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get(self, workspace_id: UUID, experiment_id: UUID) -> ExperimentDetail:
        experiment = await self._get(workspace_id, experiment_id)
        variants = list(
            (
                await self.session.scalars(
                    select(ContentExperimentVariant)
                    .where(ContentExperimentVariant.experiment_id == experiment.id)
                    .order_by(ContentExperimentVariant.created_at)
                )
            ).all()
        )
        return self._detail(experiment, variants)

    async def create(
        self, workspace_id: UUID, actor_id: UUID, payload: ExperimentCreate
    ) -> ExperimentDetail:
        experiment = ContentExperiment(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=actor_id,
            name=payload.name.strip(),
            hypothesis=payload.hypothesis,
            dimension=payload.dimension,
            source_kind=payload.source_kind,
        )
        self.session.add(experiment)
        self._audit(workspace_id, actor_id, "content_experiment.created", experiment.id)
        await self.session.commit()
        return await self.get(workspace_id, experiment.id)

    async def update(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        experiment_id: UUID,
        payload: ExperimentUpdate,
    ) -> ExperimentDetail:
        experiment = await self._get(workspace_id, experiment_id)
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(experiment, key, value)
        self._audit(workspace_id, actor_id, "content_experiment.updated", experiment.id, changes)
        await self.session.commit()
        return await self.get(workspace_id, experiment.id)

    async def add_variant(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        experiment_id: UUID,
        payload: ExperimentVariantCreate,
    ) -> ExperimentDetail:
        experiment = await self._get(workspace_id, experiment_id)
        duplicate = await self.session.scalar(
            select(ContentExperimentVariant.id).where(
                ContentExperimentVariant.experiment_id == experiment.id,
                ContentExperimentVariant.label == payload.label.strip(),
            )
        )
        if duplicate is not None:
            raise ExperimentError(
                "同一实验中的变体名称不能重复", code="variant_exists", status_code=409
            )
        content = await self._content(workspace_id, payload.content_item_id)
        publication = await self._publication(workspace_id, payload.publication_id)
        if (
            content is not None
            and publication is not None
            and publication.content_item_id != content.id
        ):
            raise ExperimentError(
                "变体关联的作品与发布记录不一致", code="evidence_mismatch", status_code=409
            )
        variant = ContentExperimentVariant(
            id=uuid4(),
            workspace_id=workspace_id,
            experiment_id=experiment.id,
            label=payload.label.strip(),
            description=payload.description,
            content_item_id=(
                content.id if content else (publication.content_item_id if publication else None)
            ),
            publication_id=publication.id if publication else None,
            exposure_at=payload.exposure_at,
            metadata_json=payload.metadata,
        )
        self.session.add(variant)
        self._audit(
            workspace_id,
            actor_id,
            "content_experiment.variant_added",
            variant.id,
            {"experiment_id": str(experiment.id), "label": variant.label},
        )
        await self.session.commit()
        return await self.get(workspace_id, experiment.id)

    async def report(
        self, workspace_id: UUID, experiment_id: UUID, window_key: ExperimentWindowKey
    ) -> ExperimentReport:
        detail = await self.get(workspace_id, experiment_id)
        variants: list[ExperimentReportVariant] = []
        for variant in detail.variants:
            attributions: list[tuple[PerformanceAttribution, Publication]] = []
            if variant.publication_id is not None:
                rows = await self.session.execute(
                    select(PerformanceAttribution, Publication)
                    .join(Publication, Publication.id == PerformanceAttribution.publication_id)
                    .where(
                        PerformanceAttribution.workspace_id == workspace_id,
                        PerformanceAttribution.publication_id == variant.publication_id,
                        PerformanceAttribution.window_key == window_key,
                        PerformanceAttribution.measurement_status == "measured",
                    )
                )
                attributions = list(rows.tuples().all())
            views = [row.view_count for row, _ in attributions if row.view_count is not None]
            interaction_rates = [
                rate
                for row, _ in attributions
                if row.view_count and row.view_count > 0
                if (rate := self._interaction_rate(row)) is not None
            ]
            completions = [
                float(row.completion_rate)
                for row, _ in attributions
                if row.completion_rate is not None
            ]
            variants.append(
                ExperimentReportVariant(
                    variant_id=variant.id,
                    label=variant.label,
                    sample_count=1 if variant.publication_id is not None else 0,
                    measured_count=len(attributions),
                    average_views=self._average(views),
                    average_interaction_rate=self._average(interaction_rates),
                    average_completion_rate=self._average(completions),
                    source_kinds=sorted(
                        {
                            cast(ExperimentSourceKind, row.source_kind)
                            for row, _ in attributions
                            if row.source_kind in {"live", "imported", "mock"}
                        }
                    ),
                    evidence=[
                        {
                            "publication_id": str(publication.id),
                            "attribution_id": str(attribution.id),
                            "source_kind": attribution.source_kind,
                            "captured_at": attribution.captured_at.isoformat()
                            if attribution.captured_at
                            else None,
                        }
                        for attribution, publication in attributions
                    ],
                )
            )
        return ExperimentReport(
            experiment=detail,
            window_key=window_key,
            variants=variants,
            caveats=[
                "这是基于真实发布归因的描述性观察，不是随机 A/B 测试，也不代表因果关系。",
                "只有已关联发布记录且该窗口已有 measured 归因时才计入样本。",
                "不同发布时间、平台、受众和分发条件未自动校正。",
            ],
        )

    async def _get(self, workspace_id: UUID, experiment_id: UUID) -> ContentExperiment:
        item = await self.session.scalar(
            select(ContentExperiment).where(
                ContentExperiment.workspace_id == workspace_id,
                ContentExperiment.id == experiment_id,
            )
        )
        if item is None:
            raise ExperimentError(
                "实验不存在或不属于当前工作区", code="experiment_not_found", status_code=404
            )
        return item

    async def _content(self, workspace_id: UUID, content_id: UUID | None) -> ContentItem | None:
        if content_id is None:
            return None
        item = await self.session.scalar(
            select(ContentItem).where(
                ContentItem.workspace_id == workspace_id, ContentItem.id == content_id
            )
        )
        if item is None:
            raise ExperimentError(
                "作品不存在或不属于当前工作区", code="content_not_found", status_code=404
            )
        return item

    async def _publication(
        self, workspace_id: UUID, publication_id: UUID | None
    ) -> Publication | None:
        if publication_id is None:
            return None
        item = await self.session.scalar(
            select(Publication).where(
                Publication.workspace_id == workspace_id, Publication.id == publication_id
            )
        )
        if item is None:
            raise ExperimentError(
                "发布记录不存在或不属于当前工作区", code="publication_not_found", status_code=404
            )
        return item

    async def _variant_counts(self, workspace_id: UUID, ids: Iterable[UUID]) -> dict[UUID, int]:
        ids = list(ids)
        if not ids:
            return {}
        rows = await self.session.execute(
            select(ContentExperimentVariant.experiment_id, func.count(ContentExperimentVariant.id))
            .where(
                ContentExperimentVariant.workspace_id == workspace_id,
                ContentExperimentVariant.experiment_id.in_(ids),
            )
            .group_by(ContentExperimentVariant.experiment_id)
        )
        return {experiment_id: int(count) for experiment_id, count in rows.all()}

    @staticmethod
    def _read(item: ContentExperiment, variant_count: int) -> ExperimentRead:
        data = ExperimentRead.model_validate(item).model_dump()
        data["variant_count"] = variant_count
        return ExperimentRead(**data)

    @staticmethod
    def _detail(
        item: ContentExperiment, variants: list[ContentExperimentVariant]
    ) -> ExperimentDetail:
        data = ExperimentRead.model_validate(item).model_dump()
        data["variant_count"] = len(variants)
        data["variants"] = [ExperimentVariantRead.model_validate(value) for value in variants]
        return ExperimentDetail(**data)

    @staticmethod
    def _average(values: Sequence[float | int | Decimal]) -> float | None:
        return round(sum(float(value) for value in values) / len(values), 6) if values else None

    @staticmethod
    def _interaction_rate(item: PerformanceAttribution) -> float | None:
        if not item.view_count or item.view_count <= 0:
            return None
        total = sum(
            value or 0
            for value in (
                item.like_count,
                item.comment_count,
                item.share_count,
                item.favorite_count,
            )
        )
        return float(total / item.view_count)

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        changes: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type="content_experiment",
                resource_id=resource_id,
                change_summary_json=changes or {},
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
