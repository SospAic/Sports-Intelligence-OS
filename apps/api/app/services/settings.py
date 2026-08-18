from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEVELOPMENT_SECRET, Settings
from app.models.operations import AuditEntry
from app.models.settings import (
    LLMProviderSetting,
    RuntimeSettingOverride,
    SyncSettings,
)
from app.providers.llm.base import LLMHealth, LLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.providers.notifications.crypto import SecretConfigCipher, mask_secret_config
from app.providers.registry import ProviderRegistry
from app.schemas.settings import (
    DEFAULT_SYNC_SETTINGS_CONFIG,
    ConfigFieldDescriptor,
    LLMModelOption,
    LLMModelsRead,
    LLMProviderSettingRead,
    LLMProviderSettingUpdate,
    LLMProviderTestRead,
    RuntimeSettingField,
    RuntimeSettingSection,
    RuntimeSettingsRead,
    SyncSettingsConfig,
    SyncSettingsRead,
    SyncSettingsUpdate,
)


class SettingsError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _secret_configured(value: SecretStr | None) -> bool:
    """Return whether a secret contains non-whitespace content."""

    return bool(value and value.get_secret_value().strip())


LLM_FIELDS = [
    ConfigFieldDescriptor(
        key="provider_id",
        label="提供商预设",
        value_type="text",
        required=True,
        default="openai",
        help_text="用于选择连接预设；协议类型与可编辑的配置名称分开保存。",
    ),
    ConfigFieldDescriptor(
        key="name",
        label="配置名称",
        value_type="text",
        required=True,
        default="OpenAI",
        help_text="工作区内显示的自定义名称，不会被协议名称覆盖。",
    ),
    ConfigFieldDescriptor(
        key="base_url",
        label="API Base URL",
        value_type="text",
        required=True,
        placeholder="https://api.openai.com/v1",
        help_text=(
            "填写 Provider 根地址，例如 https://api.openai.com/v1；粘贴 /models 或 "
            "/chat/completions 也会自动规范化。"
        ),
    ),
    ConfigFieldDescriptor(
        key="api_key",
        label="API Key",
        value_type="password",
        secret=True,
        help_text="只发送到后端并加密保存；留空会保留已有 Key。",
    ),
    ConfigFieldDescriptor(
        key="organization",
        label="Organization",
        value_type="text",
        help_text="可选，作为 OpenAI-Organization 请求头发送。",
    ),
    ConfigFieldDescriptor(
        key="project",
        label="Project",
        value_type="text",
        help_text="可选，作为 OpenAI-Project 请求头发送。",
    ),
    ConfigFieldDescriptor(
        key="custom_headers",
        label="自定义请求头",
        value_type="json",
        secret=True,
        help_text="最多 20 项；Host、Content-Length 和 Authorization 不允许覆盖。",
    ),
    ConfigFieldDescriptor(
        key="default_model",
        label="默认模型",
        value_type="text",
        required=True,
        default="gpt-5.6-terra",
    ),
    ConfigFieldDescriptor(
        key="temperature",
        label="默认 Temperature",
        value_type="number",
        default=0.4,
        minimum=0,
        maximum=2,
        step=0.1,
    ),
    ConfigFieldDescriptor(
        key="top_p",
        label="默认 Top P",
        value_type="number",
        default=1,
        minimum=0,
        maximum=1,
        step=0.05,
    ),
    ConfigFieldDescriptor(
        key="max_tokens",
        label="默认最大 Token",
        value_type="number",
        default=8192,
        minimum=1,
        maximum=131072,
        step=1,
    ),
    ConfigFieldDescriptor(
        key="timeout_seconds",
        label="请求超时（秒）",
        value_type="number",
        default=90,
        minimum=5,
        maximum=300,
        step=1,
    ),
    ConfigFieldDescriptor(
        key="max_attempts",
        label="最大尝试次数",
        value_type="number",
        default=3,
        minimum=1,
        maximum=5,
        step=1,
    ),
    ConfigFieldDescriptor(
        key="input_cost_per_million",
        label="输入成本 / 百万 Token",
        value_type="number",
        minimum=0,
        step=0.000001,
        help_text="用于成本估算；留空表示未知。",
    ),
    ConfigFieldDescriptor(
        key="output_cost_per_million",
        label="输出成本 / 百万 Token",
        value_type="number",
        minimum=0,
        step=0.000001,
        help_text="用于成本估算；留空表示未知。",
    ),
    ConfigFieldDescriptor(
        key="enabled",
        label="启用配置",
        value_type="boolean",
        default=True,
    ),
]


class SettingsService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        base_providers: ProviderRegistry[LLMProvider],
    ) -> None:
        self.session = session
        self.settings = settings
        self.base_providers = base_providers
        explicit_key = (
            settings.notification_encryption_key.get_secret_value()
            if settings.notification_encryption_key
            else ""
        )
        self.cipher = SecretConfigCipher(explicit_key or settings.secret_key.get_secret_value())

    async def runtime_settings(self) -> RuntimeSettingsRead:
        database = make_url(self.settings.database_url)
        redis = urlsplit(self.settings.redis_url)
        redis_database = redis.path.lstrip("/") or "0"
        return RuntimeSettingsRead(
            environment=self.settings.environment,
            apply_mode="environment_restart",
            warning=(
                "数据库、Redis、会话与任务进程属于部署级配置。页面只生成脱敏的环境变量草稿；"
                "必须由运维写入 .env 或 Secret 管理并重启服务，API 不会改写宿主机文件。"
            ),
            sections=[
                RuntimeSettingSection(
                    key="application",
                    title="应用与网络",
                    description="API 监听、日志、跨域与 Cookie 名称均由部署环境统一管理。",
                    fields=[
                        self._field(
                            "app_name",
                            "应用名称",
                            self.settings.app_name,
                            "text",
                            "SIO_APP_NAME",
                            "后端日志和 API 文档中的应用名称。",
                        ),
                        self._field(
                            "app_version",
                            "应用版本",
                            self.settings.app_version,
                            "text",
                            "SIO_APP_VERSION",
                            "运行实例报告的版本标识。",
                        ),
                        self._field(
                            "log_level",
                            "日志级别",
                            self.settings.log_level,
                            "text",
                            "SIO_LOG_LEVEL",
                            "建议使用 DEBUG、INFO、WARNING、ERROR 之一。",
                        ),
                        self._field(
                            "api_host",
                            "API 监听地址",
                            self.settings.api_host,
                            "text",
                            "SIO_API_HOST",
                            "容器内通常为 0.0.0.0；外部暴露范围由 Compose 端口和反向代理控制。",
                        ),
                        self._field(
                            "api_port",
                            "API 端口",
                            self.settings.api_port,
                            "number",
                            "SIO_API_PORT",
                            "FastAPI 监听端口。",
                            1,
                            65535,
                        ),
                        self._field(
                            "cors_origins",
                            "允许的 Web Origin",
                            json.dumps(self.settings.cors_origins, ensure_ascii=False),
                            "text",
                            "SIO_CORS_ORIGINS",
                            'Pydantic JSON 数组，例如 ["https://sports.example.com"]。',
                        ),
                        self._field(
                            "session_cookie_name",
                            "Session Cookie 名称",
                            self.settings.session_cookie_name,
                            "text",
                            "SIO_SESSION_COOKIE_NAME",
                            "同一域名部署多个实例时应保持唯一。",
                        ),
                    ],
                ),
                RuntimeSettingSection(
                    key="database",
                    title="PostgreSQL / 数据库",
                    description="连接标识已脱敏；连接池参数在 API、Worker 和 Beat 重启后生效。",
                    fields=[
                        self._field(
                            "database_driver",
                            "驱动",
                            database.drivername,
                            "text",
                            "SIO_DATABASE_URL",
                            "SQLAlchemy 异步驱动；连接 URL 由部署环境管理。",
                        ),
                        self._field(
                            "database_host",
                            "主机",
                            database.host or "local-file",
                            "text",
                            "SIO_DATABASE_URL",
                            "数据库主机；密码永不返回前端。",
                        ),
                        self._field(
                            "database_port",
                            "端口",
                            database.port,
                            "number",
                            "SIO_DATABASE_URL",
                            "数据库监听端口。",
                            1,
                            65535,
                        ),
                        self._field(
                            "database_name",
                            "数据库",
                            database.database,
                            "text",
                            "SIO_DATABASE_URL",
                            "数据库名（PostgreSQL 连接串中的数据库部分）。",
                        ),
                        self._field(
                            "database_username",
                            "用户名",
                            database.username,
                            "text",
                            "SIO_DATABASE_URL",
                            "连接用户名。",
                        ),
                        self._field(
                            "database_password_configured",
                            "密码已配置",
                            bool(database.password),
                            "boolean",
                            "SIO_DATABASE_URL",
                            "只显示是否存在，不显示密码。",
                            secret=True,
                        ),
                        self._field(
                            "database_pool_size",
                            "连接池基础连接数",
                            self.settings.database_pool_size,
                            "number",
                            "SIO_DATABASE_POOL_SIZE",
                            "每个进程的持久连接池大小。",
                            1,
                            100,
                        ),
                        self._field(
                            "database_max_overflow",
                            "突发额外连接数",
                            self.settings.database_max_overflow,
                            "number",
                            "SIO_DATABASE_MAX_OVERFLOW",
                            "连接池耗尽时允许临时创建的连接数。",
                            0,
                            200,
                        ),
                        self._field(
                            "database_pool_timeout_seconds",
                            "获取连接超时",
                            self.settings.database_pool_timeout_seconds,
                            "number",
                            "SIO_DATABASE_POOL_TIMEOUT_SECONDS",
                            "等待池中连接的最长秒数。",
                            1,
                            300,
                        ),
                        self._field(
                            "database_pool_recycle_seconds",
                            "连接回收周期",
                            self.settings.database_pool_recycle_seconds,
                            "number",
                            "SIO_DATABASE_POOL_RECYCLE_SECONDS",
                            "主动回收长连接以避开网络设备空闲超时。",
                            60,
                            86400,
                        ),
                        self._field(
                            "database_command_timeout_seconds",
                            "SQL 命令超时",
                            self.settings.database_command_timeout_seconds,
                            "number",
                            "SIO_DATABASE_COMMAND_TIMEOUT_SECONDS",
                            "单条数据库命令的最长秒数。",
                            1,
                            600,
                        ),
                    ],
                ),
                RuntimeSettingSection(
                    key="redis",
                    title="Redis / Celery",
                    description=(
                        "Redis 同时承载缓存、Celery Broker 与结果后端；凭证只显示配置状态。"
                    ),
                    fields=[
                        self._field(
                            "redis_scheme",
                            "协议",
                            redis.scheme,
                            "text",
                            "SIO_REDIS_URL",
                            "redis 或 rediss。",
                        ),
                        self._field(
                            "redis_host",
                            "主机",
                            redis.hostname,
                            "text",
                            "SIO_REDIS_URL",
                            "Redis 主机。",
                        ),
                        self._field(
                            "redis_port",
                            "端口",
                            redis.port or 6379,
                            "number",
                            "SIO_REDIS_URL",
                            "Redis 监听端口。",
                            1,
                            65535,
                        ),
                        self._field(
                            "redis_database",
                            "数据库编号",
                            redis_database,
                            "text",
                            "SIO_REDIS_URL",
                            "Redis logical database。",
                        ),
                        self._field(
                            "redis_credentials_configured",
                            "凭证已配置",
                            bool(redis.password),
                            "boolean",
                            "SIO_REDIS_URL",
                            "只显示是否存在，不显示密码。",
                            secret=True,
                        ),
                        self._field(
                            "redis_connect_timeout_seconds",
                            "连接超时",
                            self.settings.redis_connect_timeout_seconds,
                            "number",
                            "SIO_REDIS_CONNECT_TIMEOUT_SECONDS",
                            "建立 TCP/TLS 连接的最长秒数。",
                            0.5,
                            60,
                        ),
                        self._field(
                            "redis_socket_timeout_seconds",
                            "读写超时",
                            self.settings.redis_socket_timeout_seconds,
                            "number",
                            "SIO_REDIS_SOCKET_TIMEOUT_SECONDS",
                            "单次 Redis 读写的最长秒数。",
                            0.5,
                            60,
                        ),
                        self._field(
                            "redis_max_connections",
                            "最大连接数",
                            self.settings.redis_max_connections,
                            "number",
                            "SIO_REDIS_MAX_CONNECTIONS",
                            "每个 API 进程的连接池上限。",
                            5,
                            1000,
                        ),
                        self._field(
                            "redis_health_check_interval_seconds",
                            "连接健康检查周期",
                            self.settings.redis_health_check_interval_seconds,
                            "number",
                            "SIO_REDIS_HEALTH_CHECK_INTERVAL_SECONDS",
                            "空闲连接再次使用前的健康检查周期；0 表示关闭。",
                            0,
                            300,
                        ),
                        self._field(
                            "redis_retry_on_timeout",
                            "超时自动重试",
                            self.settings.redis_retry_on_timeout,
                            "boolean",
                            "SIO_REDIS_RETRY_ON_TIMEOUT",
                            "只针对安全的 Redis 客户端超时重试。",
                        ),
                    ],
                ),
                RuntimeSettingSection(
                    key="integrations",
                    title="平台与外部集成",
                    description="外部凭证仅回传是否配置；真实请求仍受 Adapter 能力与来源边界约束。",
                    fields=[
                        self._field(
                            "youtube_api_key_configured",
                            "YouTube Data API Key",
                            _secret_configured(self.settings.youtube_api_key),
                            "boolean",
                            "SIO_YOUTUBE_API_KEY",
                            "只用于 YouTube 官方公开 Data API；不代表 Analytics OAuth 已实现。",
                            secret=True,
                        ),
                        self._field(
                            "tiktok_api_credentials_configured",
                            "TikTok Display API 凭证",
                            bool(
                                self.settings.tiktok_client_key
                                and _secret_configured(self.settings.tiktok_client_secret)
                                and _secret_configured(self.settings.tiktok_access_token)
                            ),
                            "boolean",
                            (
                                "SIO_TIKTOK_CLIENT_KEY / SIO_TIKTOK_CLIENT_SECRET / "
                                "SIO_TIKTOK_ACCESS_TOKEN"
                            ),
                            (
                                "只表示必填字段存在；当前 Token 仍需通过官方实时 canary，"
                                "不能据此认定有效。"
                            ),
                            secret=True,
                        ),
                        self._field(
                            "douyin_api_credentials_configured",
                            "抖音开放平台凭证",
                            bool(
                                self.settings.douyin_client_key
                                and _secret_configured(self.settings.douyin_client_secret)
                                and _secret_configured(self.settings.douyin_access_token)
                            ),
                            "boolean",
                            (
                                "SIO_DOUYIN_CLIENT_KEY / SIO_DOUYIN_CLIENT_SECRET / "
                                "SIO_DOUYIN_ACCESS_TOKEN"
                            ),
                            "只表示必填字段存在；仍需按抖音开放平台权限完成官方 canary。",
                            secret=True,
                        ),
                    ],
                ),
                RuntimeSettingSection(
                    key="tasks",
                    title="同步与后台任务",
                    description="控制平台调用、任务租约和分页，不覆盖单渠道/单 Provider 配置。",
                    fields=[
                        self._field(
                            "platform_request_timeout_seconds",
                            "平台请求超时",
                            self.settings.platform_request_timeout_seconds,
                            "number",
                            "SIO_PLATFORM_REQUEST_TIMEOUT_SECONDS",
                            "平台 Adapter 单次请求超时。",
                            1,
                            60,
                        ),
                        self._field(
                            "platform_request_max_attempts",
                            "平台最大尝试次数",
                            self.settings.platform_request_max_attempts,
                            "number",
                            "SIO_PLATFORM_REQUEST_MAX_ATTEMPTS",
                            "包括首次请求在内。",
                            1,
                            5,
                        ),
                        self._field(
                            "platform_canary_enabled",
                            "平台官方 API 自动探针",
                            self.settings.platform_canary_enabled,
                            "boolean",
                            "SIO_PLATFORM_CANARY_ENABLED",
                            "仅探测已配置的官方 API 凭证；不会自动访问公开页或登录会话。",
                        ),
                        self._field(
                            "platform_canary_interval_seconds",
                            "平台探针间隔",
                            self.settings.platform_canary_interval_seconds,
                            "number",
                            "SIO_PLATFORM_CANARY_INTERVAL_SECONDS",
                            "低频探测间隔，失败会去重升级，恢复后自动关闭内部告警。",
                            900,
                            86400,
                        ),
                        self._field(
                            "sync_task_max_retries",
                            "同步任务最大重试",
                            await self.effective_sync_task_max_retries(),
                            "number",
                            "SIO_SYNC_TASK_MAX_RETRIES",
                            (
                                "Celery 同步任务重试上限；可在「设置中心 → 同步」页调整，"
                                "立即生效无需重启。"
                            ),
                            0,
                            10,
                            restart_required=False,
                        ),
                        self._field(
                            "task_stale_after_seconds",
                            "任务失联租约",
                            self.settings.task_stale_after_seconds,
                            "number",
                            "SIO_TASK_STALE_AFTER_SECONDS",
                            "超过该时间的运行会进入失联恢复。",
                            1860,
                            86400,
                        ),
                        self._field(
                            "sync_page_limit",
                            "单次同步分页上限",
                            self.settings.sync_page_limit,
                            "number",
                            "SIO_SYNC_PAGE_LIMIT",
                            "限制一次任务读取的外部分页数。",
                            1,
                            200,
                        ),
                        self._field(
                            "notification_request_timeout_seconds",
                            "通知全局超时",
                            self.settings.notification_request_timeout_seconds,
                            "number",
                            "SIO_NOTIFICATION_REQUEST_TIMEOUT_SECONDS",
                            "未设置单渠道值时的默认值。",
                            1,
                            60,
                        ),
                        self._field(
                            "notification_request_max_attempts",
                            "通知全局尝试次数",
                            self.settings.notification_request_max_attempts,
                            "number",
                            "SIO_NOTIFICATION_REQUEST_MAX_ATTEMPTS",
                            "未设置单渠道值时的默认值。",
                            1,
                            5,
                        ),
                    ],
                ),
                RuntimeSettingSection(
                    key="security",
                    title="会话与安全",
                    description="安全密钥不通过该接口返回；生产配置必须由 Secret 管理。",
                    fields=[
                        self._field(
                            "session_cookie_secure",
                            "Secure Cookie",
                            self.settings.session_cookie_secure,
                            "boolean",
                            "SIO_SESSION_COOKIE_SECURE",
                            "生产 HTTPS 必须启用。",
                        ),
                        self._field(
                            "session_ttl_seconds",
                            "会话有效期",
                            self.settings.session_ttl_seconds,
                            "number",
                            "SIO_SESSION_TTL_SECONDS",
                            "登录会话有效秒数。",
                            900,
                            2592000,
                        ),
                        self._field(
                            "auth_login_window_seconds",
                            "登录限流窗口",
                            self.settings.auth_login_window_seconds,
                            "number",
                            "SIO_AUTH_LOGIN_WINDOW_SECONDS",
                            "统计失败登录尝试的滚动窗口秒数。",
                            60,
                            86400,
                        ),
                        self._field(
                            "auth_login_max_attempts_per_identity",
                            "单账号失败上限",
                            self.settings.auth_login_max_attempts_per_identity,
                            "number",
                            "SIO_AUTH_LOGIN_MAX_ATTEMPTS_PER_IDENTITY",
                            "窗口内同一哈希身份允许的失败次数。",
                            3,
                            100,
                        ),
                        self._field(
                            "auth_login_max_attempts_per_ip",
                            "单 IP 失败上限",
                            self.settings.auth_login_max_attempts_per_ip,
                            "number",
                            "SIO_AUTH_LOGIN_MAX_ATTEMPTS_PER_IP",
                            "窗口内同一哈希客户端地址允许的失败次数。",
                            10,
                            10000,
                        ),
                        self._field(
                            "auth_attempt_retention_seconds",
                            "登录审计保留期",
                            self.settings.auth_attempt_retention_seconds,
                            "number",
                            "SIO_AUTH_ATTEMPT_RETENTION_SECONDS",
                            "只保留哈希身份、哈希 IP、时间和结果。",
                            3600,
                            7776000,
                        ),
                        self._field(
                            "session_cleanup_retention_seconds",
                            "失效会话保留期",
                            self.settings.session_cleanup_retention_seconds,
                            "number",
                            "SIO_SESSION_CLEANUP_RETENTION_SECONDS",
                            "过期或撤销会话在定时清理前的审计保留时间。",
                            3600,
                            7776000,
                        ),
                        self._field(
                            "password_min_length",
                            "密码最短长度",
                            self.settings.password_min_length,
                            "number",
                            "SIO_PASSWORD_MIN_LENGTH",
                            "新密码与管理员初始化策略。",
                            12,
                            128,
                        ),
                        self._field(
                            "secret_key_configured",
                            "独立会话密钥已配置",
                            self.settings.secret_key.get_secret_value() != DEVELOPMENT_SECRET,
                            "boolean",
                            "SIO_SECRET_KEY",
                            "开发默认值不计为独立密钥；生产必须替换，内容绝不返回。",
                            secret=True,
                        ),
                        self._field(
                            "notification_encryption_key_configured",
                            "通知加密密钥已配置",
                            bool(self.settings.notification_encryption_key),
                            "boolean",
                            "SIO_NOTIFICATION_ENCRYPTION_KEY",
                            "绝不返回密钥内容。",
                            secret=True,
                        ),
                    ],
                ),
                RuntimeSettingSection(
                    key="media_runtime",
                    title="媒体解析运行时",
                    description=(
                        "YouTube 完整解析需要 Node.js 22+；EJS 默认随 yt-dlp[default] 安装。"
                        "路径修改后需重启 API、Worker 与 Beat。"
                    ),
                    fields=[
                        self._field(
                            "ytdlp_node_path",
                            "Node.js 可执行文件路径",
                            self.settings.ytdlp_node_path,
                            "text",
                            "SIO_YTDLP_NODE_PATH",
                            "留空时从 PATH 自动查找；Docker 默认使用 /usr/local/bin/node。",
                        ),
                        self._field(
                            "ytdlp_remote_components",
                            "EJS 远程组件",
                            self.settings.ytdlp_remote_components,
                            "text",
                            "SIO_YTDLP_REMOTE_COMPONENTS",
                            "可选 ejs:github；只有镜像未包含 yt-dlp-ejs 时才需要。",
                        ),
                        self._field(
                            "ytdlp_allow_runtime_update",
                            "允许运行时更新 yt-dlp",
                            self.settings.ytdlp_allow_runtime_update,
                            "boolean",
                            "SIO_YTDLP_ALLOW_RUNTIME_UPDATE",
                            "默认关闭；生产环境建议通过重新构建镜像更新，避免容器重启后丢失。",
                        ),
                    ],
                ),
                RuntimeSettingSection(
                    key="subtitle_runtime",
                    title="本地字幕与翻译",
                    description=(
                        "字幕生成在独立 subtitle-worker 队列中执行，不会占用账号同步和"
                        "普通下载 worker。"
                        "配置修改后需要重启 API、subtitle-worker 与相关任务进程。"
                    ),
                    fields=[
                        self._field(
                            "subtitle_asr_enabled",
                            "启用本地语音识别",
                            self.settings.subtitle_asr_enabled,
                            "boolean",
                            "SIO_SUBTITLE_ASR_ENABLED",
                            "没有平台原字幕时，允许使用 faster-whisper 从本地视频生成字幕。",
                        ),
                        self._field(
                            "subtitle_asr_backend",
                            "语音识别后端",
                            self.settings.subtitle_asr_backend,
                            "text",
                            "SIO_SUBTITLE_ASR_BACKEND",
                            "当前支持 none 或 faster_whisper；未配置时不会伪造字幕结果。",
                        ),
                        self._field(
                            "subtitle_asr_model",
                            "Whisper 模型",
                            self.settings.subtitle_asr_model,
                            "text",
                            "SIO_SUBTITLE_ASR_MODEL",
                            "模型首次使用时缓存到 subtitle_models 卷；模型越大质量越高、"
                            "资源消耗越大。",
                        ),
                        self._field(
                            "subtitle_asr_device",
                            "识别设备",
                            self.settings.subtitle_asr_device,
                            "text",
                            "SIO_SUBTITLE_ASR_DEVICE",
                            "auto、cpu 或 cuda。",
                        ),
                        self._field(
                            "subtitle_asr_compute_type",
                            "计算精度",
                            self.settings.subtitle_asr_compute_type,
                            "text",
                            "SIO_SUBTITLE_ASR_COMPUTE_TYPE",
                            "int8 适合 CPU；float16 / int8_float16 适合支持 CUDA 的环境。",
                        ),
                        self._field(
                            "subtitle_asr_model_dir",
                            "模型缓存目录",
                            self.settings.subtitle_asr_model_dir,
                            "text",
                            "SIO_SUBTITLE_ASR_MODEL_DIR",
                            "建议使用持久化目录，避免容器重建后重复下载模型。",
                        ),
                        self._field(
                            "subtitle_translation_backend",
                            "本地翻译后端",
                            self.settings.subtitle_translation_backend,
                            "text",
                            "SIO_SUBTITLE_TRANSLATION_BACKEND",
                            "当前支持 none 或 http；HTTP 后端应提供 /translate 接口。",
                        ),
                        self._field(
                            "subtitle_translation_base_url",
                            "本地翻译服务地址",
                            self.settings.subtitle_translation_base_url,
                            "text",
                            "SIO_SUBTITLE_TRANSLATION_BASE_URL",
                            "例如 http://translation:8080；服务未配置时任务会明确显示翻译降级。",
                        ),
                        self._field(
                            "subtitle_translation_timeout_seconds",
                            "翻译请求超时（秒）",
                            self.settings.subtitle_translation_timeout_seconds,
                            "number",
                            "SIO_SUBTITLE_TRANSLATION_TIMEOUT_SECONDS",
                            "单批翻译请求的最大等待时间。",
                            5,
                            900,
                        ),
                        self._field(
                            "subtitle_translation_max_segments",
                            "单次最大字幕段数",
                            self.settings.subtitle_translation_max_segments,
                            "number",
                            "SIO_SUBTITLE_TRANSLATION_MAX_SEGMENTS",
                            "防止超长字幕任务占满本地翻译服务。",
                            1,
                            20_000,
                        ),
                        self._field(
                            "subtitle_translation_api_key_configured",
                            "翻译服务密钥",
                            bool(self.settings.subtitle_translation_api_key),
                            "boolean",
                            "SIO_SUBTITLE_TRANSLATION_API_KEY",
                            "只显示是否已配置，不返回密钥内容。",
                            secret=True,
                        ),
                    ],
                ),
            ],
        )

    async def sync_settings(self, workspace_id: UUID) -> SyncSettingsRead:
        """Return the workspace's global fetch policy, with defaults filled in."""

        row = await self._sync_settings_row(workspace_id)
        effective = await self.effective_sync_task_max_retries()
        return self._sync_settings_read(row, effective)

    async def update_sync_settings(
        self, workspace_id: UUID, actor_id: UUID, payload: SyncSettingsUpdate
    ) -> SyncSettingsRead:
        """Persist the workspace's global fetch policy and audit the change."""

        config = payload.config.model_dump()
        row = await self._sync_settings_row(workspace_id)
        if row is None:
            row = SyncSettings(
                id=uuid4(),
                workspace_id=workspace_id,
                config=config,
            )
            self.session.add(row)
            action = "sync_settings.created"
        else:
            row.config = config
            action = "sync_settings.updated"
        # ``sync_task_max_retries`` is a *global* server setting, but it is
        # persisted through this per-workspace endpoint so both retry knobs sit
        # on the one Sync panel. ``None`` leaves the existing override untouched
        # (partial config edits must not wipe it); an int sets it; an explicit
        # JSON null clears it back to the environment default.
        if payload.sync_task_max_retries is not None:
            await self.set_runtime_override(
                "sync_task_max_retries", int(payload.sync_task_max_retries), actor_id
            )
        self._audit(
            workspace_id,
            actor_id,
            action,
            row.id,
            {"config_keys": sorted(config.keys())},
        )
        await self.session.commit()
        await self.session.refresh(row)
        effective = await self.effective_sync_task_max_retries()
        return self._sync_settings_read(row, effective)

    async def get_runtime_override(self, key: str) -> Any | None:
        """Return the stored override value for ``key``, or ``None`` if unset."""

        row = await self.session.scalar(
            select(RuntimeSettingOverride).where(RuntimeSettingOverride.key == key)
        )
        return row.value_json if row is not None else None

    async def set_runtime_override(self, key: str, value: Any, actor_id: UUID | None) -> None:
        """Upsert a global runtime override (effective without restart)."""

        row = await self.session.scalar(
            select(RuntimeSettingOverride).where(RuntimeSettingOverride.key == key)
        )
        if row is None:
            row = RuntimeSettingOverride(key=key, value_json=value, updated_by=actor_id)
            self.session.add(row)
        else:
            row.value_json = value
            row.updated_at = datetime.now(UTC)
            row.updated_by = actor_id

    async def effective_sync_task_max_retries(self) -> int:
        """Effective sync-task retry cap: runtime override if set, else env."""

        override = await self.get_runtime_override("sync_task_max_retries")
        if isinstance(override, int) and 0 <= override <= 10:
            return override
        return int(self.settings.sync_task_max_retries)

    async def _sync_settings_row(self, workspace_id: UUID) -> SyncSettings | None:
        return cast(
            SyncSettings | None,
            await self.session.scalar(
                select(SyncSettings).where(SyncSettings.workspace_id == workspace_id)
            ),
        )

    def _sync_settings_read(
        self, row: SyncSettings | None, sync_task_max_retries: int
    ) -> SyncSettingsRead:
        if row is None:
            return SyncSettingsRead(
                config=SyncSettingsConfig(**DEFAULT_SYNC_SETTINGS_CONFIG),
                sync_task_max_retries=sync_task_max_retries,
            )
        stored = dict(row.config or {})
        merged: dict[str, Any] = {**DEFAULT_SYNC_SETTINGS_CONFIG, **stored}
        merged["yt_dlp"] = {
            **DEFAULT_SYNC_SETTINGS_CONFIG["yt_dlp"],
            **(stored.get("yt_dlp") or {}),
        }
        return SyncSettingsRead(
            config=SyncSettingsConfig(**merged),
            sync_task_max_retries=sync_task_max_retries,
        )

    async def llm_setting(self, workspace_id: UUID) -> LLMProviderSettingRead:
        setting = await self._llm_row(workspace_id)
        return self._llm_read(setting)

    async def update_llm_setting(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: LLMProviderSettingUpdate,
    ) -> LLMProviderSettingRead:
        setting = await self._llm_row(workspace_id)
        existing: dict[str, Any] = self.cipher.decrypt(setting.config_encrypted) if setting else {}
        incoming = payload.model_dump(
            exclude={
                "api_key",
                "clear_api_key",
                "default_model",
                "temperature",
                "top_p",
                "max_tokens",
                "input_cost_per_million",
                "output_cost_per_million",
                "enabled",
                "name",
            }
        )
        config = {
            **existing,
            **{key: value for key, value in incoming.items() if value is not None},
        }
        if payload.api_key is not None:
            config["api_key"] = payload.api_key.get_secret_value()
        elif payload.clear_api_key:
            config.pop("api_key", None)
        for optional_key in ("organization", "project"):
            optional_value = getattr(payload, optional_key)
            if optional_value:
                config[optional_key] = optional_value
            else:
                config.pop(optional_key, None)
        if payload.custom_headers is not None:
            config["custom_headers"] = payload.custom_headers
        config["base_url"] = payload.base_url
        config["timeout_seconds"] = payload.timeout_seconds
        config["max_attempts"] = payload.max_attempts
        provider = self._provider_from_config(
            config,
            enabled=payload.enabled,
            display_name=payload.name,
        )
        try:
            await provider.validate_config({})
        except Exception as exc:
            if payload.enabled and config.get("api_key"):
                raise SettingsError(
                    str(exc), code="llm_configuration_invalid", status_code=422
                ) from exc

        default_parameters = {
            "temperature": payload.temperature,
            "top_p": payload.top_p,
            "max_tokens": payload.max_tokens,
        }
        if setting is None:
            setting = LLMProviderSetting(
                id=uuid4(),
                workspace_id=workspace_id,
                provider_key="openai_compatible",
                name=payload.name,
                config_encrypted=self.cipher.encrypt(config),
                config_masked=mask_secret_config(config),
                default_model=payload.default_model,
                default_parameters=default_parameters,
                input_cost_per_million=payload.input_cost_per_million,
                output_cost_per_million=payload.output_cost_per_million,
                enabled=payload.enabled,
                last_tested_at=None,
                health_status="unknown",
            )
            self.session.add(setting)
            action = "llm_provider_setting.created"
        else:
            setting.name = payload.name
            setting.config_encrypted = self.cipher.encrypt(config)
            setting.config_masked = mask_secret_config(config)
            setting.default_model = payload.default_model
            setting.default_parameters = default_parameters
            setting.input_cost_per_million = payload.input_cost_per_million
            setting.output_cost_per_million = payload.output_cost_per_million
            setting.enabled = payload.enabled
            setting.health_status = "unknown"
            action = "llm_provider_setting.updated"
        self._audit(
            workspace_id,
            actor_id,
            action,
            setting.id,
            {
                "provider_key": setting.provider_key,
                "enabled": setting.enabled,
                "api_key_configured": bool(config.get("api_key")),
                "changed_fields": sorted(payload.model_fields_set - {"api_key"}),
            },
        )
        await self.session.commit()
        await self.session.refresh(setting)
        return self._llm_read(setting)

    async def test_llm_setting(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: LLMProviderSettingUpdate | None = None,
    ) -> LLMProviderTestRead:
        """Probe the saved or currently edited connection.

        The previous endpoint ignored the form and always resolved the old
        database row.  A form can now send its current values, so operators
        can test before saving.  Unsaved probes are deliberately not written
        into the saved row; otherwise the status panel would report a healthy
        connection for a different configuration.
        """

        setting = await self._llm_row(workspace_id)
        config = await self._llm_config(workspace_id, setting)
        display_name = setting.name if setting is not None else "部署级 LLM 配置"
        persist_result = payload is None and setting is not None
        if payload is not None:
            config = self._merge_llm_payload(config, payload)
            display_name = payload.name
        provider = self._provider_from_config(
            config,
            enabled=True,
            display_name=display_name,
        )
        provider_id = str(config.get("provider_id") or "openai")
        default_model = (
            payload.default_model
            if payload is not None
            else setting.default_model
            if setting is not None
            else self.settings.llm_default_model
        )
        tested_at = datetime.now(UTC)
        model_count: int | None = None
        model_available: bool | None = None
        try:
            if not isinstance(provider, OpenAICompatibleProvider):
                raise SettingsError(
                    "当前配置的协议适配器尚未实现",
                    code="llm_provider_test_unsupported",
                    status_code=422,
                )
            rows = await provider.list_models()
            model_count = len(rows)
            model_ids = {str(row.get("id")) for row in rows if row.get("id")}
            model_available = default_model in model_ids if model_ids else None
            if not rows:
                health = LLMHealth(
                    status="degraded",
                    detail=(
                        "连接与认证成功，但 Provider 没有返回可用模型；请检查模型权限或 "
                        "手动填写模型 ID。"
                    ),
                )
            elif model_available is False:
                health = LLMHealth(
                    status="degraded",
                    detail=(
                        f"连接成功，返回 {len(rows)} 个模型，但默认模型 {default_model} "
                        "不在清单中。"
                    ),
                )
            else:
                health = LLMHealth(
                    status="ok",
                    detail=f"连接与认证成功，已读取 {len(rows)} 个模型；未发起计费生成请求。",
                )
        except Exception as exc:
            health = LLMHealth(status="unavailable", detail=str(exc))
        if persist_result and setting is not None:
            setting.last_tested_at = tested_at
            setting.health_status = (
                "healthy"
                if health.status == "ok"
                else "degraded"
                if health.status == "degraded"
                else "unhealthy"
            )
            self._audit(
                workspace_id,
                actor_id,
                "llm_provider_setting.tested",
                setting.id,
                {
                    "status": health.status,
                    "provider_id": provider_id,
                    "default_model": default_model,
                    "model_available": model_available,
                    "model_count": model_count,
                },
            )
            await self.session.commit()
        return LLMProviderTestRead(
            status=health.status,
            detail=health.detail,
            tested_at=tested_at,
            provider_id=provider_id,
            default_model=default_model,
            model_available=model_available,
            model_count=model_count,
            persisted=persist_result,
        )

    async def llm_models(self, workspace_id: UUID) -> LLMModelsRead:
        provider = await self.resolve_llm_provider(workspace_id, "openai_compatible")
        setting = await self._llm_row(workspace_id)
        provider_id = "openai"
        if setting is not None:
            stored_config = self.cipher.decrypt(setting.config_encrypted)
            provider_id = str(stored_config.get("provider_id") or "openai")
        if not isinstance(provider, OpenAICompatibleProvider) or not provider.configured:
            return LLMModelsRead(
                provider_key="openai_compatible",
                provider_id=provider_id,
                source="unavailable",
                detail=(
                    "请先保存并启用可用的 Base URL 与 API Key；Ollama 等本地 Provider "
                    "可不填 Key。"
                ),
            )
        try:
            rows = await provider.list_models()
        except Exception as exc:
            return LLMModelsRead(
                provider_key="openai_compatible",
                provider_id=provider_id,
                source="unavailable",
                detail=str(exc),
            )
        return LLMModelsRead(
            provider_key="openai_compatible",
            provider_id=provider_id,
            source="live",
            items=[LLMModelOption.model_validate(row) for row in rows],
            detail="已从当前 Provider 的 /models 接口读取",
        )

    async def resolve_llm_provider(self, workspace_id: UUID, key: str) -> LLMProvider:
        if key != "openai_compatible":
            try:
                return self.base_providers.get(key)
            except LookupError as exc:
                raise SettingsError(
                    "未知 LLM Provider", code="llm_provider_unknown", status_code=422
                ) from exc
        setting = await self._llm_row(workspace_id)
        if setting is None:
            return self.base_providers.get(key)
        config = self.cipher.decrypt(setting.config_encrypted)
        return self._provider_from_config(
            config,
            enabled=setting.enabled,
            display_name=setting.name,
        )

    async def effective_llm_defaults(
        self, workspace_id: UUID
    ) -> tuple[str, dict[str, Any], Decimal | None, Decimal | None]:
        setting = await self._llm_row(workspace_id)
        if setting is None:
            return (
                self.settings.llm_default_model,
                {
                    "temperature": self.settings.llm_default_temperature,
                    "top_p": self.settings.llm_default_top_p,
                    "max_tokens": self.settings.llm_default_max_tokens,
                },
                None,
                None,
            )
        return (
            setting.default_model,
            dict(setting.default_parameters),
            setting.input_cost_per_million,
            setting.output_cost_per_million,
        )

    async def _llm_row(self, workspace_id: UUID) -> LLMProviderSetting | None:
        return cast(
            LLMProviderSetting | None,
            await self.session.scalar(
                select(LLMProviderSetting).where(
                    LLMProviderSetting.workspace_id == workspace_id,
                    LLMProviderSetting.provider_key == "openai_compatible",
                )
            ),
        )

    def _llm_read(self, setting: LLMProviderSetting | None) -> LLMProviderSettingRead:
        if setting is not None:
            config = self.cipher.decrypt(setting.config_encrypted)
            provider_id = str(config.get("provider_id") or "openai")
            configured = bool(setting.enabled and config.get("base_url") and config.get("api_key"))
            if provider_id in {"ollama", "chat2api", "new-api"}:
                configured = bool(setting.enabled and config.get("base_url"))
            effective = configured and setting.enabled
            return LLMProviderSettingRead(
                id=setting.id,
                provider_key=setting.provider_key,
                provider_id=provider_id,
                provider_protocol="openai_compatible",
                name=setting.name,
                source="database",
                base_url=str(config.get("base_url")) if config.get("base_url") else None,
                api_key_configured=bool(config.get("api_key")),
                config_masked=setting.config_masked,
                default_model=setting.default_model,
                default_parameters=setting.default_parameters,
                input_cost_per_million=setting.input_cost_per_million,
                output_cost_per_million=setting.output_cost_per_million,
                enabled=setting.enabled,
                configured=configured,
                effective=effective,
                effective_scope="workspace" if effective else "none",
                effective_scope_detail=(
                    "当前工作区；新的手动生成、Worker 生成和自动化生成任务使用此配置。"
                    if effective
                    else "此配置不会参与生成任务；请启用配置并完成连接测试。"
                ),
                effective_for=(
                    ["新的手动生成", "Worker 生成", "自动化 create_generation 动作"]
                    if effective
                    else []
                ),
                last_tested_at=setting.last_tested_at,
                health_status=setting.health_status,
                health_detail=self._llm_health_detail(
                    setting.health_status, configured, setting.enabled
                ),
                updated_at=setting.updated_at,
                fields=LLM_FIELDS,
            )
        api_key = (
            self.settings.llm_openai_compatible_api_key.get_secret_value()
            if self.settings.llm_openai_compatible_api_key
            else None
        )
        configured = bool(self.settings.llm_openai_compatible_base_url and api_key)
        return LLMProviderSettingRead(
            id=None,
            provider_key="openai_compatible",
            provider_id="openai",
            provider_protocol="openai_compatible",
            name="部署级 LLM 配置",
            source="environment" if configured else "unconfigured",
            base_url=self.settings.llm_openai_compatible_base_url,
            api_key_configured=bool(api_key),
            config_masked={
                "base_url": self.settings.llm_openai_compatible_base_url,
                "api_key": "••••••••" if api_key else None,
            },
            default_model=self.settings.llm_default_model,
            default_parameters={
                "temperature": self.settings.llm_default_temperature,
                "top_p": self.settings.llm_default_top_p,
                "max_tokens": self.settings.llm_default_max_tokens,
                "timeout_seconds": self.settings.llm_request_timeout_seconds,
                "max_attempts": self.settings.llm_request_max_attempts,
            },
            input_cost_per_million=None,
            output_cost_per_million=None,
            enabled=True,
            configured=configured,
            effective=configured,
            effective_scope="environment" if configured else "none",
            effective_scope_detail=(
                "部署级环境变量；工作区保存配置后会覆盖此默认连接。"
                if configured
                else "尚未配置工作区或部署级 LLM 连接。"
            ),
            effective_for=(
                ["新的手动生成", "Worker 生成", "自动化 create_generation 动作"]
                if configured
                else []
            ),
            last_tested_at=None,
            health_status="unknown",
            health_detail=self._llm_health_detail("unknown", configured, True),
            updated_at=None,
            fields=LLM_FIELDS,
        )

    def _provider_from_config(
        self,
        config: dict[str, Any],
        *,
        enabled: bool,
        display_name: str | None = None,
    ) -> OpenAICompatibleProvider:
        provider_id = str(config.get("provider_id") or "openai")
        return OpenAICompatibleProvider(
            base_url=str(config.get("base_url")) if enabled and config.get("base_url") else None,
            api_key=str(config.get("api_key")) if enabled and config.get("api_key") else None,
            provider_id=provider_id,
            display_name=display_name,
            api_key_optional=provider_id in {"ollama", "chat2api", "new-api"},
            timeout_seconds=float(
                config.get("timeout_seconds", self.settings.llm_request_timeout_seconds)
            ),
            max_attempts=int(config.get("max_attempts", self.settings.llm_request_max_attempts)),
            organization=str(config.get("organization")) if config.get("organization") else None,
            project=str(config.get("project")) if config.get("project") else None,
            custom_headers={
                str(key): str(value)
                for key, value in dict(config.get("custom_headers") or {}).items()
            },
            internal_hosts=tuple(self.settings.llm_internal_hosts_allowlist),
        )

    async def _llm_config(
        self, workspace_id: UUID, setting: LLMProviderSetting | None
    ) -> dict[str, Any]:
        if setting is not None:
            return self.cipher.decrypt(setting.config_encrypted)
        return {
            "base_url": self.settings.llm_openai_compatible_base_url,
            "api_key": (
                self.settings.llm_openai_compatible_api_key.get_secret_value()
                if self.settings.llm_openai_compatible_api_key
                else None
            ),
            "provider_id": "openai",
            "timeout_seconds": self.settings.llm_request_timeout_seconds,
            "max_attempts": self.settings.llm_request_max_attempts,
        }

    def _merge_llm_payload(
        self, existing: dict[str, Any], payload: LLMProviderSettingUpdate
    ) -> dict[str, Any]:
        config = dict(existing)
        values = payload.model_dump(
            exclude={
                "api_key",
                "clear_api_key",
                "default_model",
                "temperature",
                "top_p",
                "max_tokens",
                "input_cost_per_million",
                "output_cost_per_million",
                "enabled",
                "name",
            }
        )
        config.update({key: value for key, value in values.items() if value is not None})
        if payload.api_key is not None:
            config["api_key"] = payload.api_key.get_secret_value()
        elif payload.clear_api_key:
            config.pop("api_key", None)
        for optional_key in ("organization", "project"):
            optional_value = getattr(payload, optional_key)
            if optional_value:
                config[optional_key] = optional_value
            else:
                config.pop(optional_key, None)
        if payload.custom_headers is not None:
            config["custom_headers"] = payload.custom_headers
        config["base_url"] = payload.base_url
        config["timeout_seconds"] = payload.timeout_seconds
        config["max_attempts"] = payload.max_attempts
        return config

    @staticmethod
    def _llm_health_detail(health_status: str, configured: bool, enabled: bool) -> str:
        if not enabled:
            return "配置已保存但未启用，不会被新的生成任务选用。"
        if not configured:
            return "缺少可用的 Base URL 或 API Key；本地 Provider 可按说明省略 API Key。"
        return {
            "healthy": "最近一次模型清单探测成功。",
            "degraded": "最近一次探测连接成功，但默认模型不可用或模型清单为空。",
            "unhealthy": "最近一次模型清单探测失败，请查看测试结果并重新验证。",
            "unknown": "配置已具备，但尚未执行真实模型清单探测。",
        }.get(health_status, "状态未知，请重新测试连接。")

    @staticmethod
    def _field(
        key: str,
        label: str,
        value: str | int | float | bool | None,
        value_type: str,
        env_var: str,
        description: str,
        minimum: float | None = None,
        maximum: float | None = None,
        *,
        secret: bool = False,
        restart_required: bool = True,
    ) -> RuntimeSettingField:
        return RuntimeSettingField(
            key=key,
            label=label,
            value=value,
            value_type=value_type,  # type: ignore[arg-type]
            env_var=env_var,
            description=description,
            secret=secret,
            restart_required=restart_required,
            minimum=minimum,
            maximum=maximum,
        )

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        changes: dict[str, Any],
    ) -> None:
        self.session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type="llm_provider_setting",
                resource_id=resource_id,
                before_hash=None,
                after_hash=None,
                change_summary_json=changes,
                reason=None,
                ip_hash=None,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
