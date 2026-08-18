from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_SECRET = "local-development-secret-replace-before-production-2026"  # noqa: S105
DEVELOPMENT_DATABASE_PASSWORD = "sio-local-development-only"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SIO_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "Sports Intelligence OS"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"  # noqa: S104 - container listener, not an auth boundary
    api_port: int = 8000

    database_url: str = (
        "postgresql+asyncpg://sio:sio-local-development-only@127.0.0.1:5432/sports_intelligence"
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=200)
    database_pool_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86_400)
    database_command_timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_connect_timeout_seconds: float = Field(default=5.0, ge=0.5, le=60.0)
    redis_socket_timeout_seconds: float = Field(default=5.0, ge=0.5, le=60.0)
    redis_max_connections: int = Field(default=50, ge=5, le=1000)
    redis_health_check_interval_seconds: int = Field(default=30, ge=0, le=300)
    redis_retry_on_timeout: bool = True

    secret_key: SecretStr = SecretStr(DEVELOPMENT_SECRET)
    session_cookie_name: str = "sio_session"
    session_cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=86_400, ge=900, le=2_592_000)
    auth_login_window_seconds: int = Field(default=900, ge=60, le=86_400)
    auth_login_max_attempts_per_identity: int = Field(default=10, ge=3, le=100)
    auth_login_max_attempts_per_ip: int = Field(default=100, ge=10, le=10_000)
    auth_attempt_retention_seconds: int = Field(default=604_800, ge=3600, le=7_776_000)
    session_cleanup_retention_seconds: int = Field(default=604_800, ge=3600, le=7_776_000)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    password_min_length: int = Field(default=12, ge=12, le=128)
    youtube_api_key: SecretStr | None = None
    # Optional server-level fallbacks for official platform adapters. These
    # remain environment-only; workspace-scoped credentials continue to take
    # precedence and are stored encrypted by PlatformCredentialService.
    tiktok_client_key: str | None = None
    tiktok_client_secret: SecretStr | None = None
    tiktok_access_token: SecretStr | None = None
    tiktok_refresh_token: SecretStr | None = None
    douyin_client_key: str | None = None
    douyin_client_secret: SecretStr | None = None
    douyin_access_token: SecretStr | None = None
    douyin_refresh_token: SecretStr | None = None
    video_search_enabled: bool = True
    video_search_default_interval_seconds: int = Field(default=3600, ge=60, le=2_592_000)
    video_search_max_candidates_per_run: int = Field(default=20, ge=1, le=200)
    video_search_analyzer: Literal["none", "gemini_video", "mock"] = "none"
    video_search_request_timeout_seconds: float = Field(default=180.0, ge=10.0, le=900.0)
    video_search_max_upload_bytes: int = Field(default=100_000_000, ge=10_000_000, le=500_000_000)
    gemini_api_key: SecretStr | None = None
    gemini_video_model: str = "gemini-3.6-flash"

    # ---- 本地语义检索（pgvector + 自托管 embedding 服务，不依赖任何外部 LLM）----
    semantic_search_enabled: bool = Field(
        default=False,
        description=(
            "Enable local vector retrieval over already-ingested content items. "
            "Requires the pgvector extension and a reachable embedding backend."
        ),
    )
    embedding_backend: Literal["none", "tei", "ollama"] = Field(
        default="none",
        description=(
            "'tei' talks to an OpenAI-compatible /v1/embeddings endpoint "
            "(HuggingFace Text Embeddings Inference, vLLM, Infinity, ...); "
            "'ollama' talks to /api/embed; 'none' disables embedding generation."
        ),
    )
    embedding_base_url: str = Field(
        default="http://embeddings:80",
        max_length=2048,
        description="Base URL of the self-hosted embedding service (Docker-internal).",
    )
    embedding_api_key: SecretStr | None = None
    embedding_model: str = Field(
        default="BAAI/bge-m3",
        max_length=240,
        description=(
            "Embedding model identifier. BGE-M3 is the default: MIT licensed, "
            "1024 dimensions, strong Chinese/English cross-lingual retrieval."
        ),
    )
    embedding_dimension: int = Field(
        default=1024,
        ge=64,
        le=4096,
        description=(
            "Vector width. MUST match the deployed model and the column type created "
            "by the alembic migration; changing it requires a re-index/backfill."
        ),
    )
    embedding_batch_size: int = Field(default=16, ge=1, le=128)
    embedding_request_timeout_seconds: float = Field(default=60.0, ge=5.0, le=600.0)
    embedding_chunk_chars: int = Field(
        default=700,
        ge=100,
        le=4000,
        description="Target characters per embedded chunk before overlap is applied.",
    )
    embedding_chunk_overlap_chars: int = Field(default=100, ge=0, le=1000)
    embedding_max_chunks_per_item: int = Field(
        default=200,
        ge=1,
        le=5000,
        description="Safety cap so one very long transcript cannot dominate a backfill run.",
    )
    # Subtitle processing runs on a dedicated Celery queue. Normal account sync
    # remains independent of model loading and CPU/GPU contention.
    subtitle_asr_enabled: bool = True
    subtitle_asr_backend: Literal["none", "faster_whisper"] = "faster_whisper"
    subtitle_asr_model: str = Field(default="small", min_length=1, max_length=120)
    subtitle_asr_device: Literal["auto", "cpu", "cuda"] = "auto"
    subtitle_asr_compute_type: Literal["int8", "int8_float16", "float16", "float32"] = "int8"
    subtitle_asr_model_dir: str = Field(default="/workspace/models/whisper", max_length=2048)
    subtitle_asr_max_file_bytes: int = Field(default=4_000_000_000, ge=1_000_000, le=20_000_000_000)
    subtitle_asr_max_duration_seconds: int = Field(default=7200, ge=60, le=86_400)
    subtitle_asr_beam_size: int = Field(default=5, ge=1, le=10)
    subtitle_translation_backend: Literal["none", "http"] = "http"
    subtitle_translation_base_url: str | None = Field(
        default="http://translation:5000", max_length=2048
    )
    subtitle_translation_api_key: SecretStr | None = None
    subtitle_translation_timeout_seconds: float = Field(default=120.0, ge=5.0, le=900.0)
    subtitle_translation_max_segments: int = Field(default=2000, ge=1, le=20_000)
    rerank_enabled: bool = Field(
        default=False,
        description=(
            "Re-score the head of the RRF-fused candidate list with a cross-feature "
            "model (vector similarity + keyword density + recency + source quality). "
            "Off by default: the fused ranking stays byte-for-byte identical."
        ),
    )
    rerank_top_n: int = Field(
        default=30,
        ge=1,
        le=200,
        description=(
            "How many fused candidates enter the rerank stage. The tail keeps its "
            "fused order, so this bounds the extra cost regardless of 'candidates'."
        ),
    )
    embedding_cache_enabled: bool = Field(
        default=True,
        description=(
            "Cache embedding vectors in-process keyed by (model, text) so repeated "
            "passages (same caption, re-embedded on re-index) never hit the backend twice."
        ),
    )
    embedding_cache_max_entries: int = Field(
        default=20000,
        ge=1,
        le=200000,
        description="LRU ceiling for the in-process embedding cache (vectors are ~4KB each).",
    )
    platform_request_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    platform_request_max_attempts: int = Field(default=3, ge=1, le=5)
    platform_canary_enabled: bool = Field(
        default=True,
        description="Enable low-frequency health probes for configured official platform APIs.",
    )
    platform_canary_interval_seconds: int = Field(
        default=3600,
        ge=900,
        le=86_400,
        description="Minimum interval between official platform API canary probes.",
    )
    hotspot_feed_max_sources: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum enabled public RSS/Atom sources sampled by one hotspot run.",
    )
    hotspot_feed_items_per_source: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum fresh entries read from each public hotspot feed.",
    )
    hotspot_feed_concurrency: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Bounded concurrency for independent public feed reads.",
    )
    hotspot_sport_query_concurrency: int = Field(
        default=3,
        ge=1,
        le=8,
        description="Bounded concurrency for the 50 + 30 live sport discovery queries.",
    )
    hotspot_sport_max_queries_per_lane: int = Field(
        default=2,
        ge=1,
        le=3,
        description=(
            "Maximum adaptive YouTube search queries per sport lane; the second query "
            "is used only when the first real result set is below target."
        ),
    )
    hotspot_mainstream_target_items: int = Field(
        default=50,
        ge=1,
        le=50,
        description="Target live hot items per mainstream sport in one collection run.",
    )
    hotspot_general_target_items: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Target live hot items per general sport in one collection run.",
    )
    sync_task_max_retries: int = Field(default=3, ge=0, le=10)
    sync_global_concurrency: int = Field(
        default=2,
        ge=1,
        le=32,
        description="Maximum number of account-sync runs across all workers.",
    )
    sync_platform_concurrency: int = Field(
        default=1,
        ge=1,
        le=16,
        description="Maximum simultaneous account-sync runs for one platform.",
    )
    sync_lease_wait_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Bounded wait before a busy sync budget is retried by Celery.",
    )
    task_stale_after_seconds: int = Field(default=2100, ge=1860, le=86_400)
    task_dispatch_timeout_seconds: int = Field(
        default=180,
        ge=30,
        le=1800,
        description=(
            "A sync run left in 'queued' with no worker pickup beyond this window is "
            "treated as stuck and auto-released, so an account is never permanently "
            "locked by a task the worker failed to dispatch."
        ),
    )
    download_stale_after_seconds: int = Field(
        default=900,
        ge=120,
        le=86_400,
        description=(
            "A queued/running download with no progress update beyond this window "
            "is closed as failed so a dead worker cannot leave a permanent spinner."
        ),
    )
    media_storage_quota_bytes: int | None = Field(
        default=None,
        ge=1,
        le=10_000_000_000_000,
        description=(
            "Optional soft quota for the media volume; health reporting never deletes files."
        ),
    )

    @field_validator("media_storage_quota_bytes", mode="before")
    @classmethod
    def _empty_media_quota_is_unset(cls, value: object) -> object:
        """Treat Compose's optional empty environment value as ``None``."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    media_storage_scan_max_files: int = Field(
        default=100_000,
        ge=100,
        le=2_000_000,
        description="Maximum files inspected by one storage health scan.",
    )
    media_lifecycle_enabled: bool = Field(
        default=False,
        description=(
            "Enable destructive media lifecycle cleanup. Keep disabled until a "
            "retention policy has been reviewed and a backup is available."
        ),
    )
    media_lifecycle_dry_run: bool = Field(
        default=True,
        description="Plan lifecycle cleanup without deleting physical files.",
    )
    media_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        description="Retention window for explicitly temporary tracked artifacts.",
    )
    media_orphan_retention_days: int = Field(
        default=7,
        ge=1,
        le=3650,
        description="Grace period before an untracked workspace media file is eligible.",
    )
    media_lifecycle_batch_size: int = Field(
        default=200,
        ge=1,
        le=10_000,
        description="Maximum physical files considered by one lifecycle execution.",
    )
    derived_metrics_bucket_seconds: int = Field(
        default=3600,
        ge=300,
        le=86_400,
        description=(
            "Bucket repeated derived-metric calculations so one entity/metric/window "
            "does not create a new row on every sync within the same interval."
        ),
    )
    derived_metrics_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        description="Retention window for reproducible derived metrics when cleanup is enabled.",
    )
    derived_metrics_cleanup_enabled: bool = Field(
        default=False,
        description="Allow the scheduled derived-metric cleanup to delete expired rows.",
    )
    derived_metrics_cleanup_dry_run: bool = Field(
        default=True,
        description="Report expired derived metrics without deleting them.",
    )
    derived_metrics_cleanup_batch_size: int = Field(
        default=50_000,
        ge=1_000,
        le=500_000,
        description="Maximum expired derived-metric rows deleted per transaction batch.",
    )
    sync_page_limit: int = Field(
        default=40,
        ge=1,
        le=200,
        description=(
            "How many content-list pages a single account sync may ingest. The "
            "engine still stops at the wall-clock budget, max_contents, or the "
            "incremental known-work boundary. 40 pages is needed because TikTok "
            "currently returns only 15 works per browser page; a lower default "
            "silently truncated new-account backfills after a few pages."
        ),
    )
    sync_stale_grace_seconds: int = Field(
        default=120,
        ge=30,
        le=1800,
        description=(
            "Slack added to sync_run_timeout_seconds to derive when a 'running' "
            "sync run is declared crashed. A run that respects its own budget can "
            "never exceed budget+grace, so anything past that lost its worker. "
            "The generic task_stale_after_seconds (2100s) is far too coarse for "
            "account sync: a crashed run would hold the account lock for 35 "
            "minutes, during which the account cannot be synced at all."
        ),
    )
    sync_page_fetch_timeout_seconds: int = Field(
        default=60,
        ge=20,
        le=600,
        description=(
            "Hard cap on a single content-list page fetch inside one sync. The "
            "page-boundary wait_for uses min(remaining_run_budget, this). Capping "
            "it BELOW the adapter's own extract timeout means a slow/unreachable "
            "channel fails the page via asyncio.wait_for (which breaks the loop "
            "and finalises what was ingested) instead of burning the whole run "
            "budget on retried extracts. Directly serves 'no long stalls'."
        ),
    )
    sync_fetch_concurrency: int = Field(
        default=4,
        ge=1,
        le=16,
        description=(
            "How many per-video metadata extractions a single account sync may "
            "run in parallel. Measured on a real YouTube channel (8 works): 28.1s "
            "sequential, 9.8s at 4, 6.8s at 8. Each adapter clamps this to its own "
            "platform ceiling (TikTok/Douyin stay low because burst traffic trips "
            "their anti-bot layer), so raising it never makes a fragile platform "
            "more aggressive than is safe. Set to 1 to restore the strictly "
            "sequential legacy behaviour."
        ),
    )
    sync_incremental_probe_size: int = Field(
        default=15,
        ge=1,
        le=200,
        description=(
            "Size of the first content-list window for an account we already "
            "track. Enumerating a channel window is itself a paid network call, "
            "so a routine sync probes only the head of the reverse-chronological "
            "catalogue and stops as soon as a whole page is already stored. Later "
            "pages widen back to the normal window when the probe turns out to be "
            "all new."
        ),
    )
    sync_fast_list_enabled: bool = Field(
        default=True,
        description=(
            "Enable the fast content-listing path: enumerate the channel window "
            "with a cheap flat catalogue read, then fully extract only the works "
            "that actually need it (new works, or all works when the workspace "
            "policy refreshes existing ones). The legacy path re-extracted every "
            "work in the window on every sync, which dominated sync wall clock. "
            "Disable to force the legacy single-shot extraction."
        ),
    )
    # yt-dlp / YouTube runtime. Node 22+ is used when present; the explicit
    # path is useful for Windows hosts and for Docker images with a fixed path.
    ytdlp_node_path: str | None = None
    ytdlp_remote_components: str = ""
    ytdlp_allow_runtime_update: bool = False
    browser_cdp_endpoint: str = Field(
        default="http://browser:9222",
        min_length=8,
        max_length=240,
        description="Docker 内置人工登录浏览器的私有 CDP 地址。",
    )
    browser_vnc_url: str = Field(
        default="http://localhost:6080/vnc.html?autoconnect=1&resize=scale",
        max_length=2048,
        description="Docker 内置人工登录浏览器的 noVNC 地址。",
    )
    sync_run_timeout_seconds: int = Field(
        default=300,
        ge=120,
        le=7200,
        description=(
            "Hard wall-clock budget for a single account sync run. When exceeded "
            "the run stops paging, commits whatever it has ingested, and finishes "
            "as success/degraded instead of running unbounded. Lowered from 1800s "
            "to 300s: a single account sync must never monopolise a worker for "
            "minutes. Keep this below SIO_TASK_STALE_AFTER_SECONDS (default 2100) "
            "so healthy-but-slow runs are never wrongly flagged as crashed by the "
            "stale-recovery watchdog."
        ),
    )

    @property
    def sync_stale_after_seconds(self) -> int:
        """When a ``running`` sync run is considered crashed.

        Derived from the run's own wall-clock budget rather than the generic
        ``task_stale_after_seconds`` so the watchdog tracks the engine: a run
        that honours its budget always finishes within
        ``sync_run_timeout_seconds``; anything beyond that plus the grace window
        lost its worker and must have its account lock released promptly.
        Never longer than the generic setting, so tightening that still applies.
        """

        derived = int(self.sync_run_timeout_seconds) + int(self.sync_stale_grace_seconds)
        return min(derived, int(self.task_stale_after_seconds))

    llm_openai_compatible_base_url: str | None = None
    llm_openai_compatible_api_key: SecretStr | None = None
    llm_default_model: str = "gpt-5.6-terra"
    llm_default_temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    llm_default_top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    llm_default_max_tokens: int = Field(default=8192, ge=1, le=131_072)
    llm_request_timeout_seconds: float = Field(default=90.0, ge=5.0, le=300.0)
    llm_request_max_attempts: int = Field(default=3, ge=1, le=5)
    notification_encryption_key: SecretStr | None = None
    notification_request_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    notification_request_max_attempts: int = Field(default=3, ge=1, le=5)
    news_ssrf_check_enabled: bool = Field(
        default=True,
        description=(
            "Enable SSRF protection for news source URLs. Disable only in an isolated "
            "environment whose DNS intentionally resolves through non-global ranges."
        ),
    )
    llm_internal_hosts_allowlist: list[str] = Field(
        default_factory=lambda: ["llm-gateway", "llm-experimental", "host.docker.internal"],
        description=(
            "Hostnames permitted to bypass SSRF public-endpoint validation for LLM "
            "base URLs. Used for Docker-internal gateway services such as New API or "
            "Chat2API sidecars."
        ),
    )
    browser_first_mode: bool = Field(
        default=False,
        description=(
            "When enabled, platform sync prefers browser adapters over API adapters "
            "to save API quota/costs. The browser adapter is used regardless of "
            "credential mode unless mode is explicitly 'api' with valid credentials."
        ),
    )
    llm_fallback_base_url: str | None = Field(
        default=None,
        description=(
            "Optional OpenAI-compatible base URL used as a fallback when the primary "
            "LLM provider fails with rate-limit or authentication errors. Typically "
            "points to the llm-experimental (gpt4free) service, e.g. "
            "'http://llm-experimental:8000/v1'."
        ),
    )

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "Settings":
        if self.environment != "production":
            return self

        secret = self.secret_key.get_secret_value()
        if secret == DEVELOPMENT_SECRET or len(secret) < 32:
            raise ValueError(
                "production requires a unique SIO_SECRET_KEY of at least 32 characters"
            )
        if DEVELOPMENT_DATABASE_PASSWORD in self.database_url:
            raise ValueError("production database URL cannot use the local development password")
        if not self.session_cookie_secure:
            raise ValueError("production requires SIO_SESSION_COOKIE_SECURE=true")
        encryption_key = (
            self.notification_encryption_key.get_secret_value()
            if self.notification_encryption_key is not None
            else ""
        )
        if len(encryption_key) < 32:
            raise ValueError(
                "production requires a unique SIO_NOTIFICATION_ENCRYPTION_KEY "
                "of at least 32 characters"
            )
        if self.llm_fallback_base_url:
            raise ValueError("production must not enable the experimental LLM fallback")
        if any(host == "llm-experimental" for host in self.llm_internal_hosts_allowlist):
            raise ValueError("production must not allow the experimental LLM host")
        if self.media_lifecycle_enabled and self.media_storage_quota_bytes is None:
            raise ValueError(
                "production media lifecycle cleanup requires an explicit storage quota"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
