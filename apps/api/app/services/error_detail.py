"""Operator- and developer-readable detail for every failure in the operation trail.

The system operation trail (sync runs, audit entries, system events, external
call attempts, outbox/dead-letter attempts, background task runs, generation and
news runs, ...) records failures in many tables. To keep those failures
*actionable* rather than opaque, every error now carries two complementary
strings produced by the helpers below:

* ``code_level_detail`` — the *code-level* detail (concrete exception class +
  message, originating adapter, run / request / trace ids) so a developer can
  debug without scraping raw logs.
* ``business_hint_for`` — the *business-layer* explanation + remediation mapped
  from the error code, so an operator knows *what the failure means for this
  operation* and *what to do next* instead of facing a bare error string.

This module is the single source of truth reused by ``sync.py`` and the
operation/audit/log writers so the two strings stay consistent everywhere.
"""

from __future__ import annotations

from uuid import UUID


def code_level_detail(
    exc: BaseException | None,
    *,
    run: object | None = None,
    run_id: UUID | None = None,
    request_id: str | None = None,
    adapter_key: str | None = None,
    trace_id: UUID | None = None,
    resource: str | None = None,
) -> str:
    """Build the code-level error detail string for operator/developer debugging.

    Includes the concrete exception class + message, the originating adapter and
    the run / request / trace ids so a failure can be traced without grepping
    logs. ``run`` may be any object exposing ``id`` and ``request_id`` (e.g. a
    ``SyncRun``); the remaining keyword args let callers supply ids directly when
    no run object is available.
    """

    parts: list[str] = []
    if exc is not None:
        parts.append(f"{type(exc).__module__}.{type(exc).__qualname__}: {exc}")
    if adapter_key:
        parts.append(f"adapter={adapter_key}")
    if run is not None:
        run_id_value = getattr(run, "id", None)
        if run_id_value is not None:
            parts.append(f"run={run_id_value}")
        req = (getattr(run, "request_id", None) or "").strip()
        if req:
            parts.append(f"request_id={req}")
    if run_id is not None:
        parts.append(f"run={run_id}")
    if request_id:
        parts.append(f"request_id={request_id}")
    if trace_id is not None:
        parts.append(f"trace_id={trace_id}")
    if resource:
        parts.append(resource)
    return " | ".join(parts) if parts else "no code-level detail captured"


# Operation/audit-trail error codes -> business-layer explanation + remediation.
_BUSINESS_HINTS: dict[str, str] = {
    # --- sync / adapter (kept from sync.py) ---
    "login_required": (
        "该平台内容需要登录后才能访问（登录墙）。请在「设置 → 平台管理」中"
        "配置该平台的登录态 / 凭证后重试。"
    ),
    "authentication_error": (
        "平台凭证无效或已过期。请检查对应平台的 API Key / Token 配置是否正确且未失效。"
    ),
    "permission_denied": "当前凭证缺少所需权限。请确认平台应用已获得相应授权范围（scope）。",
    "not_found": (
        "账号不存在、已被平台隐藏或已删除。请检查网址是否正确，或该内容是否仅对登录用户可见。"
    ),
    "rate_limited": ("触发了平台限流。系统会自动有限重试；若持续失败，请降低抓取频率或稍后再试。"),
    "transient_provider_error": (
        "平台或网络暂时不可用（可能是限流、反爬或临时故障）。系统会自动有限重试；"
        "如反复失败可稍后手动重试。"
    ),
    "adapter_configuration_error": (
        "采集方式未正确配置（缺少凭证或未满足公开页条件）。请检查平台管理中的采集配置。"
    ),
    "contract_mapping_error": (
        "平台返回的数据结构异常，无法映射到统一模型。可能是页面改版或反爬，可重试；若持续请反馈开发。"
    ),
    "capability_not_supported": "该操作所需的平台能力未实现。",
    "adapter_not_implemented": "该平台适配器尚未实现，暂不支持同步。",
    "account_not_found": "同步目标账号已被删除。",
    "unexpected_sync_error": (
        "同步过程出现未预期错误。代码级详情已记录，可将本错误信息反馈给开发排查。"
    ),
    "queue_dispatch_failed": (
        "后台任务队列不可用，同步任务未被消费。请检查 Celery worker 是否正常运行。"
    ),
    "dispatch_timeout": (
        "同步任务已入队但长时间未被 worker 接收，可能 broker 不可用。请检查 Celery worker。"
    ),
    "stale_task_recovered": (
        "同步任务执行超时（worker 可能中途崩溃），已自动释放锁。可重新发起同步。"
    ),
    "retry_exhausted": "已重试多次仍失败，停止自动重试。请根据上方错误详情排查后手动重试。",
    "sync_budget_exhausted": (
        "本次同步已用尽时间预算（含队列等待与失败重试），已主动终止并释放账号锁。"
        "可立即重新发起同步；若频繁出现，请降低并发或调大同步超时。"
    ),
    "account_metrics_extraction_failed": (
        "已更新账号资料，但指标提取失败（部分字段需官方 API / 登录授权）。不影响作品同步。"
    ),
    # --- operation / automation domain ---
    "automation_rule_not_found": "自动化规则不存在或已被删除。",
    "automation_disabled": "该自动化已禁用，不会触发。如需运行请先启用。",
    "trigger_condition_unmet": "触发条件未满足，自动化未执行。",
    "template_render_error": (
        "通知模板渲染失败（变量缺失或模板语法错误）。请检查模板与变量 schema。"
    ),
    "delivery_failed": "通知投递失败。请检查渠道配置与接收地址是否正确。",
    "webhook_delivery_failed": "Webhook 投递失败。请确认回调地址可达且返回 2xx。",
    "generation_provider_error": ("生成模型供应商返回错误。请检查 API Key / 额度 / 模型名称配置。"),
    "generation_timeout": "生成任务超时。可重试，或降低输入规模 / 切换模型。",
    "news_sync_error": "资讯同步失败。请检查资讯源配置、凭证与网络连通性。",
    "external_call_failed": "外部调用失败。请检查目标服务可用性、凭证与网络。",
    "outbox_publish_failed": "领域事件发布失败。系统会按退避策略自动重试。",
    "llm_call_failed": "LLM 调用失败。请检查模型供应商凭证、额度或超时设置。",
    "media_lifecycle_partial_failure": (
        "媒体生命周期清理仅部分完成。请检查文件权限、存储连通性与代码级详情，"
        "确认失败文件后再手动重试。"
    ),
    "operation_failed": "操作执行失败。请结合代码级错误详情定位原因，必要时联系管理员。",
}


def business_hint_for(
    code: str | None,
    *,
    adapter_key: str | None = None,
    category: str | None = None,
) -> str:
    """Return a business-layer explanation + remediation for an error code.

    This is the operator-facing counterpart to the raw ``error_detail``: it tells
    the person running the operation *what the failure means* and *what to do
    next*. Unmapped / missing codes fall back to a generic but useful hint that
    lists the most common causes so the field is never empty for a real failure.
    """

    # Never surface a literal "(unknown)": an unmapped / missing code means the
    # failure was not categorised, not that the cause is genuinely unknown. A
    # generic, actionable hint is far less confusing for operators than a token
    # that looks like a bug in the error layer itself.
    base = _BUSINESS_HINTS.get(code or "") or (
        "操作执行失败。常见原因：依赖的下游服务不可用、"
        "凭证过期或权限不足、网络中断或触发限流、入参校验未通过。"
        "请结合代码级错误详情定位，必要时联系管理员。"
    )
    if adapter_key:
        return f"{base}（适配器：{adapter_key}）"
    if category:
        return f"{base}（类型：{category}）"
    return base
