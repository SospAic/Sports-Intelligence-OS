"""Build explicit, non-secret capability readiness reports.

This module contains no network calls. It answers "can this workflow be
started from the current configuration?" while deliberately distinguishing
that from "did a live provider probe succeed?".
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, cast

from app.core.config import Settings
from app.schemas.readiness import (
    PlatformCanaryRead,
    PlatformReadinessRead,
    ReadinessItemRead,
    ReadinessReportRead,
    ReadinessStatus,
)
from app.schemas.settings import PlatformCredentialRead
from app.services.platform_credentials import REQUIRED_API_FIELDS

_FIELD_LABELS = {
    "api_key": "官方 API Key",
    "client_key": "Client Key",
    "client_secret": "Client Secret",
    "access_token": "Access Token",
    "refresh_token": "Refresh Token",
}


def _field_label(field: str) -> str:
    return _FIELD_LABELS.get(field, field)


def _configured_secret(value: Any) -> bool:
    if value is None:
        return False
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    return bool(str(value).strip())


def build_platform_readiness(
    *,
    platform: Any,
    adapter_descriptor: Any | None,
    credential: PlatformCredentialRead,
    last_probe: PlatformCanaryRead | None = None,
) -> PlatformReadinessRead:
    """Translate adapter and credential state into an actionable report item."""

    adapter_key = str(getattr(platform, "adapter_key", ""))
    descriptor_status = cast(
        Literal["implemented", "skeleton"],
        getattr(adapter_descriptor, "implementation_status", "skeleton"),
    )
    capabilities = {
        str(capability.value if hasattr(capability, "value") else capability): bool(supported)
        for capability, supported in (
            getattr(adapter_descriptor, "capabilities", {}) or {}
        ).items()
    }
    source_kinds = sorted(
        str(item) for item in (getattr(adapter_descriptor, "source_kinds", ()) or ())
    )
    configured_fields = sorted(credential.configured_fields)
    missing: list[str] = []
    conditions: list[str] = []
    status: ReadinessStatus

    if descriptor_status != "implemented":
        status = "blocked"
        detail = "当前平台适配器仍是骨架，不能启动真实同步。"
        conditions.append("完成该平台适配器的真实调用、错误分类和契约测试")
        next_action = "先完成适配器实现后再接入账号"
    elif credential.configured:
        # Configuration is not a successful live probe. This distinction keeps
        # expired/revoked OAuth tokens from being shown as production-ready.
        if last_probe is None:
            status = "unverified"
            detail = "采集策略或凭证已满足启动条件，但尚未由应用执行实时平台探针。"
            conditions.append("执行该平台的官方 API / 合法公开页实时探针并记录结果")
            next_action = "运行一次平台探针，再开始账号同步"
        elif last_probe.status == "passed":
            status = "ready"
            detail = f"最近一次平台探针通过（{last_probe.checked_at.isoformat()}）。"
            conditions.append("按平台配额和数据新鲜度 SLO 定期重跑探针")
            next_action = "继续同步；若出现失败，先查看探针错误码"
        elif last_probe.status == "degraded":
            status = "degraded"
            detail = f"最近一次平台探针部分可用：{last_probe.detail}"
            conditions.append("检查探针详情和缺失字段，不要把部分可用当作完整指标")
            next_action = "修复降级字段或确认该平台能力边界"
        elif last_probe.status == "blocked":
            status = "needs_setup"
            detail = f"最近一次探针未执行：{last_probe.detail}"
            conditions.append("补齐探针执行所需的凭证、许可或运行时条件")
            next_action = "补齐条件后重新运行平台探针"
        else:
            status = "blocked"
            detail = f"最近一次平台探针失败：{last_probe.detail}"
            conditions.append("修复探针报告的凭证、权限、限流或网络问题")
            next_action = "处理失败原因后重新运行平台探针"
    else:
        status = "needs_setup"
        if credential.mode == "api":
            required = REQUIRED_API_FIELDS.get(credential.platform_key, set())
            missing = sorted(field for field in required if field not in configured_fields)
            labels = [_field_label(field) for field in missing]
            detail = "官方 API 模式尚未满足必填凭证条件。"
            conditions.append(
                "补齐：" + "、".join(labels or ["平台官方凭证"]) + "，并完成实时探针"
            )
            next_action = "在平台管理中补齐凭证，或切换到合法公开页采集并完成确认"
        elif credential.mode == "public_page":
            detail = "公开页采集策略尚未完成合规确认，系统不会启动采集。"
            conditions.extend(
                [
                    "确认平台许可与服务条款",
                    "复核 robots 与访问边界",
                    "启用字段最小化、来源审计，并设置至少 300 秒采样间隔",
                ]
            )
            next_action = "完成公开页采集政策确认后再同步"
        else:
            detail = "授权登录或会话尚未满足保存条件。"
            conditions.append("完成账号授权、平台许可和 OAuth 不足条件确认")
            next_action = "重新完成人工授权或保存有效会话"

    if not capabilities.get("ACCOUNT_ANALYTICS", False):
        conditions.append("账号分析字段需要该平台适配器明确支持")
    if not capabilities.get("CONTENT_ANALYTICS", False):
        conditions.append("作品分析字段需要该平台适配器明确支持")

    return PlatformReadinessRead(
        key=f"platform:{platform.key}",
        title=f"{platform.name} 数据采集",
        platform_key=platform.key,
        platform_name=platform.name,
        adapter_key=adapter_key,
        adapter_implementation_status=descriptor_status,
        credential_mode=credential.mode,
        credential_source=credential.source,
        configured_fields=configured_fields,
        missing_configuration=missing,
        capabilities=capabilities,
        source_kinds=source_kinds,
        status=status,
        detail=detail,
        conditions=conditions,
        next_action=next_action,
        last_probe=last_probe,
    )


def build_feature_readiness(settings: Settings) -> list[ReadinessItemRead]:
    """Expose cross-platform gaps without pretending unavailable features work."""

    semantic_ready = bool(
        settings.semantic_search_enabled and settings.embedding_backend != "none"
    )
    if semantic_ready:
        semantic_status: ReadinessStatus = "unverified"
        semantic_detail = "文本语义检索已启用；索引覆盖率和 embedding 服务可用性仍需运行时检查。"
        semantic_conditions = ["检查 embedding 服务健康状态并完成待索引内容回填"]
        semantic_next = "在语义检索设置中检查索引覆盖率"
    else:
        semantic_status = "needs_setup"
        semantic_detail = "文本语义检索依赖 pgvector、启用开关和可访问的 embedding 后端。"
        semantic_conditions = [
            "启用 SIO_SEMANTIC_SEARCH_ENABLED",
            "将 SIO_EMBEDDING_BACKEND 设置为 tei 或 ollama",
            "完成索引回填",
        ]
        semantic_next = "配置 embedding 后端后执行索引回填"

    video_ai_ready = bool(
        settings.video_search_enabled
        and settings.video_search_analyzer == "gemini_video"
        and _configured_secret(settings.gemini_api_key)
    )
    keyframe_detail = (
        "视频分析模型已配置，但当前仍没有可审计的关键帧抽取与关键帧向量索引流水线。"
        if video_ai_ready
        else "关键帧抽取、关键帧向量化和多模态检索尚未形成可运行闭环。"
    )

    return [
        ReadinessItemRead(
            key="channel_resource_permissions",
            title="频道级 / 发布资源权限",
            status="blocked",
            detail=(
                "当前权限模型覆盖工作区、账号和成员访问，但没有平台频道级或"
                "发布资源级 OAuth scope 与授权对象。"
            ),
            conditions=[
                "平台提供资源级 OAuth scope",
                "保存授权对象与资源 external_id 的映射",
                "发布动作通过真实 publish adapter 并保留审计回执",
            ],
            next_action="先实现资源授权模型，再接入发布适配器",
        ),
        ReadinessItemRead(
            key="private_analytics_and_experiments",
            title="私有 Analytics / A/B / 因果分析",
            status="blocked",
            detail=(
                "当前指标来自公开数据或派生计算，不等于平台私有 Analytics；"
                "没有授权流量来源、留存、受众和实验分流数据。"
            ),
            conditions=[
                "取得对应平台私有 Analytics OAuth scope",
                "建立实验分流、曝光、转化和归因事件表",
                "完成预注册指标、样本量和因果识别假设",
            ],
            next_action="先完成私有 Analytics 授权与事件采集，再上线实验分析",
        ),
        ReadinessItemRead(
            key="keyframe_multimodal_index",
            title="关键帧与多模态索引",
            status="blocked",
            detail=keyframe_detail,
            conditions=[
                "实现 ffmpeg / PyAV 关键帧抽取与时间戳存储",
                "为关键帧建立媒体 artifact、模型和版本可追溯记录",
                "配置多模态 embedding 后端并把关键帧接入混合检索",
            ],
            next_action="先落地关键帧 artifact 与索引任务，再接入多模态模型",
        ),
        ReadinessItemRead(
            key="semantic_text_search",
            title="字幕 / 文本语义检索",
            status=semantic_status,
            detail=semantic_detail,
            conditions=semantic_conditions,
            next_action=semantic_next,
        ),
    ]


def build_readiness_report(
    *,
    settings: Settings,
    platforms: list[Any],
    credentials: list[PlatformCredentialRead],
    registry: Any,
    last_probes: Mapping[str, PlatformCanaryRead] | None = None,
) -> ReadinessReportRead:
    credential_by_key = {item.platform_key: item for item in credentials}
    platform_items: list[PlatformReadinessRead] = []
    for platform in platforms:
        credential = credential_by_key.get(platform.key)
        if credential is None:
            continue
        descriptor = None
        try:
            descriptor = registry.get(platform.adapter_key).descriptor
        except (LookupError, AttributeError):
            descriptor = None
        platform_items.append(
            build_platform_readiness(
                platform=platform,
                adapter_descriptor=descriptor,
                credential=credential,
                last_probe=(last_probes or {}).get(platform.key),
            )
        )
    return ReadinessReportRead(
        generated_at=datetime.now(UTC),
        platforms=platform_items,
        features=build_feature_readiness(settings),
    )
