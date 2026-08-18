export type SourceKind = "live" | "imported" | "mock";

export type WorkspaceRole = "owner" | "admin" | "editor" | "analyst" | "viewer";

export interface UserSummary {
  id: string;
  email: string;
  display_name: string;
  locale: string;
  timezone: string;
}

export interface WorkspaceMembershipSummary {
  workspace_id: string;
  workspace_name: string;
  role: WorkspaceRole;
}

export interface CurrentUserResponse {
  user: UserSummary;
  memberships: WorkspaceMembershipSummary[];
}

export interface AuthResponse {
  user: UserSummary;
  csrf_token: string;
  expires_at: string;
}

export interface CsrfResponse {
  csrf_token: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  service: string;
  version: string;
  checks?: Record<string, "ok" | "error">;
}

export type AccountSyncStatus =
  | "never"
  | "queued"
  | "syncing"
  | "success"
  | "degraded"
  | "error"
  | "disabled";

export interface PlatformSummary {
  id: string;
  key: string;
  name: string;
  adapter_key: string;
}

export interface MonitoringAccountSummary {
  id: string;
  platform: PlatformSummary;
  display_name: string;
  username: string | null;
  source_kind: SourceKind;
  sync_status: AccountSyncStatus;
  last_synced_at: string | null;
  next_sync_at: string | null;
  last_sync_error_code: string | null;
  last_sync_error_message: string | null;
}

export interface MonitoringAccountPage {
  items: MonitoringAccountSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  code: string;
  detail: string;
  instance?: string;
  request_id?: string;
  errors?: Array<{
    path: string;
    code: string;
    message: string;
  }>;
}

export type EditorialRuleType =
  | "principle"
  | "qualification"
  | "research"
  | "narrative"
  | "language"
  | "structure"
  | "fact_check"
  | "length"
  | "output"
  | "qa"
  | "rewrite"
  | "tts"
  | "ssml"
  | "title"
  | "search_keyword"
  | "material_search";

export interface EditorialRuleSetSummary {
  id: string;
  key: string;
  name: string;
  description: string | null;
  current_version_id: string | null;
  status: "active" | "disabled" | "archived";
  tags: string[];
  version_count: number;
  draft_count: number;
  created_at: string;
  updated_at: string;
}

export interface EditorialRuleVersionSummary {
  id: string;
  version: string;
  source_hash: string;
  changelog: string | null;
  status: "draft" | "published" | "archived";
  created_by: string;
  created_at: string;
  published_at: string | null;
}

export interface EditorialRuleSetDetail extends EditorialRuleSetSummary {
  versions: EditorialRuleVersionSummary[];
}

export interface EditorialRuleVersion extends EditorialRuleVersionSummary {
  rule_set_id: string;
  source_text: string;
  section_count: number;
  rule_count: number;
}

export interface EditorialRule {
  id: string;
  version_id: string;
  section_id: string;
  key: string;
  title: string;
  rule_type: EditorialRuleType;
  instruction: string;
  why: string | null;
  how: string | null;
  good_example: string | null;
  bad_example: string | null;
  qa_check: string | null;
  rewrite_instruction: string | null;
  priority: number;
  severity: "info" | "warning" | "error" | "critical";
  is_mandatory: boolean;
  enabled: boolean;
  sports: string[];
  story_types: string[];
  output_types: string[];
  dependencies: string[];
  conflicts: string[];
  tags: string[];
  source_reference: string | null;
  source_status: "full" | "partial" | "unresolved";
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface EditorialRuleSectionNode {
  id: string;
  version_id: string;
  parent_id: string | null;
  title: string;
  slug: string;
  description: string | null;
  sort_order: number;
  rules: EditorialRule[];
  children: EditorialRuleSectionNode[];
}

export interface EditorialRuleTree {
  version: EditorialRuleVersionSummary;
  sections: EditorialRuleSectionNode[];
  total_rules: number;
}

export interface EditorialRuleSetPage {
  items: EditorialRuleSetSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface PromptVersionSummary {
  id: string;
  collection_id: string;
  version: string;
  changelog: string | null;
  status: "draft" | "published" | "archived";
  created_at: string;
  published_at: string | null;
}

export interface PromptVersion extends PromptVersionSummary {
  system_prompt: string;
  user_prompt_template: string;
  variables_schema: Record<string, unknown>;
  model_config: Record<string, unknown>;
  created_by: string;
}

export interface PromptCollectionSummary {
  id: string;
  key: string;
  name: string;
  description: string | null;
  category: string;
  current_version_id: string | null;
  status: "active" | "disabled" | "archived";
  tags: string[];
  created_at: string;
  updated_at: string;
  version_count: number;
}

export interface PromptCollectionDetail extends PromptCollectionSummary {
  versions: PromptVersionSummary[];
}

export interface PromptCollectionPage {
  items: PromptCollectionSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface GenerationWorkflow {
  id: string;
  key: string;
  name: string;
  description: string | null;
  input_types: string[];
  steps: Array<{
    key: string;
    name: string;
    sort_order: number;
    required: boolean;
  }>;
  default_rule_set_version_id: string | null;
  default_prompt_version_id: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface LLMProviderDescriptor {
  key: string;
  provider_id?: string;
  name: string;
  configured: boolean;
  is_mock: boolean;
  supports_streaming: boolean;
  detail: string;
  source: "database" | "environment" | "builtin" | "unconfigured";
  default_model: string | null;
  default_parameters: Record<string, unknown>;
}

export interface RuntimeSettingField {
  key: string;
  label: string;
  value: string | number | boolean | null;
  value_type: "text" | "number" | "boolean";
  env_var: string;
  description: string;
  secret: boolean;
  restart_required: boolean;
  minimum: number | null;
  maximum: number | null;
}

export interface RuntimeSettingSection {
  key: string;
  title: string;
  description: string;
  fields: RuntimeSettingField[];
}

export interface RuntimeSettingsRecord {
  environment: string;
  sections: RuntimeSettingSection[];
  apply_mode: "environment_restart";
  warning: string;
}

export interface YtDlpRuntimeRecord {
  node_configured_path: string | null;
  node_resolved_path: string | null;
  node_available: boolean;
  node_version: string | null;
  yt_dlp_version: string | null;
  ejs_package_expected: boolean;
  remote_components: string[];
  update_enabled: boolean;
  update_command: string;
  update_note: string;
  status: "ready" | "degraded";
  detail: string;
}

export interface YtDlpSettings {
  dateafter: string;
  datebefore: string;
  playlist_start: number;
  daterange: string;
  playlist_items: string;
  playlist_reverse: boolean;
  playlist_random: boolean;
  no_playlist: boolean;
  flat_playlist: boolean;
  sort: string;
  match_filter: string;
  match_title: string;
  reject_title: string;
  age_limit: number | null;
  min_duration: number | null;
  max_duration: number | null;
  min_filesize: string;
  max_filesize: string;
  proxy: string;
  socket_timeout: number | null;
  retries: number | null;
  fragment_retries: number | null;
  sleep_interval: number | null;
  max_sleep_interval: number | null;
  sleep_requests: number | null;
  limit_rate: string;
  geo_bypass: boolean;
  geo_bypass_country: string;
  geo_verification_proxy: string;
  cookies_from_browser:
    | ""
    | "brave"
    | "chrome"
    | "chromium"
    | "edge"
    | "firefox"
    | "opera"
    | "safari"
    | "vivaldi"
    | "whale";
  ignore_errors: boolean;
  no_warnings: boolean;
  extra_args: Record<string, unknown>;
}

export interface YtDlpDownloadSettings {
  write_thumbnail: boolean;
  write_subtitles: boolean;
  write_auto_subtitles: boolean;
  subtitle_langs: string;
  download_video: boolean;
  video_format: string;
  write_info_json: boolean;
  /** Opt-in: persist the current Top 20 hot comments per work. */
  fetch_comments: boolean;
}

export interface SyncSettingsConfig {
  /** Max works a single sync ingests; null = full catalogue (bounded by pagination). */
  max_contents: number | null;
  /** Skip already-known works (only refresh metrics) instead of overwriting. */
  skip_existing: boolean;
  yt_dlp: YtDlpSettings;
  download: YtDlpDownloadSettings;
}

export interface SyncSettingsRecord {
  config: SyncSettingsConfig;
  /** Effective sync-task retry cap (runtime override if set, else env default). */
  sync_task_max_retries: number;
}

export interface LLMProviderSettingRecord {
  id: string | null;
  provider_key: string;
  provider_id: string;
  provider_protocol: "openai_compatible";
  name: string;
  source: "database" | "environment" | "unconfigured";
  base_url: string | null;
  api_key_configured: boolean;
  config_masked: Record<string, unknown>;
  default_model: string;
  default_parameters: Record<string, unknown>;
  input_cost_per_million: string | number | null;
  output_cost_per_million: string | number | null;
  enabled: boolean;
  configured: boolean;
  effective: boolean;
  effective_scope: "workspace" | "environment" | "none";
  effective_scope_detail: string;
  effective_for: string[];
  last_tested_at: string | null;
  health_status: string;
  health_detail: string;
  updated_at: string | null;
  fields: ConfigFieldDescriptor[];
}

export interface LLMProviderTestResult {
  status: "ok" | "degraded" | "unavailable";
  detail: string;
  tested_at: string;
  provider_id: string;
  default_model: string | null;
  model_available: boolean | null;
  model_count: number | null;
  persisted: boolean;
}

export interface LLMModelOption {
  id: string;
  name: string;
  owned_by: string | null;
}

export interface LLMModelsResult {
  provider_key: string;
  provider_id: string;
  source: "live" | "catalog" | "unavailable";
  items: LLMModelOption[];
  detail: string | null;
}

export interface GenerationStep {
  id: string;
  step_key: string;
  name: string;
  sort_order: number;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown> | null;
  prompt_snapshot: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  error: Record<string, unknown> | null;
}

export interface GenerationRun {
  id: string;
  workflow_id: string;
  input_type: string;
  input_id: string | null;
  input_payload: Record<string, unknown>;
  rule_set_version_id: string;
  prompt_version_id: string;
  provider: string;
  model: string;
  model_config: Record<string, unknown>;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  current_step: string | null;
  verification_status: string;
  started_at: string | null;
  completed_at: string | null;
  raw_output: Record<string, unknown> | null;
  final_output: Record<string, unknown> | null;
  validation_result: Record<string, unknown>;
  rewrite_count: number;
  token_usage: Record<string, unknown>;
  estimated_cost: string | number | null;
  error: { code?: string; message?: string } | null;
  metadata: Record<string, unknown>;
  is_saved: boolean;
  user_rating: number | null;
  created_at: string;
  updated_at: string;
  steps: GenerationStep[];
}

export interface GenerationRunPage {
  items: GenerationRun[];
  page: number;
  page_size: number;
  total: number;
}

export interface GenerationEvidencePackage {
  contract_version: string;
  run_id: string;
  input_hash: string;
  frozen_at: string | null;
  source_kind: string;
  verification_status: string;
  evidence_status: "available" | "partial" | "unavailable";
  evidence_detail: string;
  source_count: number;
  sources: Array<Record<string, unknown>>;
  claims: Array<Record<string, unknown>>;
  timeline: Array<Record<string, unknown>>;
  qualification: Record<string, unknown>;
  step_statuses: Array<Record<string, unknown>>;
  output_references: Array<Record<string, unknown>>;
}

export type EditorialStatus =
  | "draft"
  | "in_review"
  | "approved"
  | "rejected"
  | "archived";

export interface EditorialItem {
  id: string;
  workspace_id: string;
  generation_run_id: string;
  created_by: string;
  assignee_id: string | null;
  title: string;
  status: EditorialStatus;
  priority: number;
  due_at: string | null;
  content_snapshot: Record<string, unknown>;
  source_snapshot: Record<string, unknown>;
  requested_at: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface EditorialItemPage {
  items: EditorialItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface EditorialComment {
  id: string;
  workspace_id: string;
  editorial_item_id: string;
  author_id: string;
  body: string;
  resolved_at: string | null;
  resolved_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface EditorialMember {
  id: string;
  display_name: string;
  email: string;
  role: WorkspaceRole;
}

export interface EditorialSavedView {
  id: string;
  workspace_id: string;
  created_by: string;
  name: string;
  status: EditorialStatus | null;
  assignee_id: string | null;
  overdue: boolean;
  unassigned: boolean;
  priority_min: number | null;
  priority_max: number | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformRecord extends PlatformSummary {
  category: string;
  enabled: boolean;
  capabilities: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AdapterConfigFieldRead {
  key: string;
  label: string;
  required: boolean;
  secret: boolean;
  description: string | null;
}

export interface AdapterDescriptorRead {
  key: string;
  name: string;
  implementation_status: "implemented" | "skeleton";
  capabilities: Record<string, boolean>;
  config_fields: AdapterConfigFieldRead[];
  source_kinds: string[];
}

export type ReadinessStatus =
  | "ready"
  | "unverified"
  | "degraded"
  | "needs_setup"
  | "blocked";

export interface ReadinessItemRead {
  key: string;
  title: string;
  status: ReadinessStatus;
  detail: string;
  conditions: string[];
  next_action: string;
}

export interface PlatformCanaryRead {
  platform_key: string;
  adapter_key: string;
  trigger: "manual" | "scheduled";
  mode: "api" | "public_page" | "authorized_login" | "authorized_session";
  credential_source: "database" | "environment" | "default";
  status: "passed" | "degraded" | "failed" | "blocked";
  checked_at: string;
  detail: string;
  error_code: string | null;
  duration_ms: number | null;
  response_summary: Record<string, string | number | boolean | null>;
}

export interface PlatformReadinessRead extends ReadinessItemRead {
  platform_key: string;
  platform_name: string;
  adapter_key: string;
  adapter_implementation_status: "implemented" | "skeleton";
  credential_mode:
    | "api"
    | "public_page"
    | "authorized_login"
    | "authorized_session";
  credential_source: "database" | "environment" | "default";
  configured_fields: string[];
  missing_configuration: string[];
  capabilities: Record<string, boolean>;
  source_kinds: string[];
  last_probe: PlatformCanaryRead | null;
}

export interface ReadinessReportRead {
  generated_at: string;
  platforms: PlatformReadinessRead[];
  features: ReadinessItemRead[];
}

export interface AccountSnapshot {
  id: string;
  account_id: string;
  captured_at: string;
  follower_count: number | null;
  following_count: number | null;
  total_like_count: number | null;
  total_view_count: number | null;
  video_count: number | null;
  engagement_rate: number | null;
  metadata: Record<string, unknown>;
  source_kind: SourceKind;
  source_provider: string;
  fetched_at: string;
}

export interface AccountRecord extends MonitoringAccountSummary {
  workspace_id: string;
  platform_id: string;
  platform: PlatformRecord;
  external_id: string;
  profile_url: string | null;
  avatar_url: string | null;
  description: string | null;
  country: string | null;
  language: string | null;
  is_verified: boolean | null;
  is_active: boolean;
  metadata: Record<string, unknown>;
  sync_interval_seconds: number;
  source_provider: string;
  fetched_at: string;
  source_url: string | null;
  created_at: string;
  updated_at: string;
  latest_snapshot: AccountSnapshot | null;
  follower_growth_24h: number | null;
  sync_settings_override?: AccountSyncSettingsOverride | null;
}

export interface AccountRecordPage {
  items: AccountRecord[];
  page: number;
  page_size: number;
  total: number;
}

export interface AccountSyncFetchSettings {
  /** 单次抓取数量上限; null = 沿用工作区默认（全量，受分页上限约束）。 */
  max_contents: number | null;
  /** 抓取范围起始日期 (YYYYMMDD); null = 不限制。 */
  dateafter: string | null;
  /** 抓取范围截止日期 (YYYYMMDD); null = 不限制。 */
  datebefore: string | null;
  /** 起始位置 (1-based 偏移，跳过前 N 条); null = 从头开始。 */
  playlist_start: number | null;
}

export interface AccountSyncSettingsOverride {
  /** Per-account download policy, deep-merged over the workspace sync settings. */
  download: YtDlpDownloadSettings;
  /** Per-account fetch window (count / date range / start); null = inherit. */
  fetch?: AccountSyncFetchSettings | null;
}

export interface AccountSnapshotPage {
  items: AccountSnapshot[];
  page: number;
  page_size: number;
  total: number;
}

export interface AccountMetricsHistoryPoint {
  captured_at: string;
  follower_count: number | null;
  following_count: number | null;
  total_like_count: number | null;
  total_view_count: number | null;
  video_count: number | null;
}

export interface AccountMetricsHistory {
  account_id: string;
  days: number;
  points: AccountMetricsHistoryPoint[];
}

/**
 * Aggregated content-level overview for an account (backend
 * `GET /accounts/{id}/content-summary`). Every field is derived from real
 * snapshots the adapter returned; API-dependent fields (completion rate,
 * traffic split, watch time) come back as `null` when the account's adapter
 * path could not obtain them, and the UI renders the required condition.
 */
export interface AccountContentSummary {
  account_id: string;
  content_count: number;
  avg_completion_rate: number | null;
  avg_watch_time_seconds: number | null;
  avg_engagement_rate: number | null;
  total_like_count: number | null;
  total_comment_count: number | null;
  total_share_count: number | null;
  total_favorite_count: number | null;
  total_interactions: number | null;
  calculated_engagement_rate: number | null;
  calculated_like_rate: number | null;
  calculated_comment_rate: number | null;
  calculated_share_rate: number | null;
  calculated_favorite_rate: number | null;
  content_total_view_count: number | null;
  account_total_likes: number | null;
  account_total_views: number | null;
  traffic_source_split: Record<string, number | null>;
  recent_24h_view_growth: number | null;
  recent_24h_view_growth_estimated: boolean;
  recent_24h_view_growth_sample_size: number | null;
  recent_24h_view_growth_actual_window_hours: number | null;
  top_content_id: string | null;
  top_content_title: string | null;
  top_content_views: number | null;
}

export interface ContentSnapshot {
  id: string;
  content_item_id: string;
  captured_at: string;
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  share_count: number | null;
  favorite_count: number | null;
  follower_gain: number | null;
  average_watch_time: number | null;
  completion_rate: number | null;
  search_traffic_rate: number | null;
  recommendation_traffic_rate: number | null;
  profile_traffic_rate: number | null;
  revenue: number | null;
  rpm: number | null;
  metadata: Record<string, unknown>;
  source_kind: SourceKind;
  source_provider: string;
  fetched_at: string;
}

export interface ContentRecord {
  id: string;
  workspace_id: string;
  platform_id: string;
  platform: PlatformRecord;
  account_id: string;
  external_id: string;
  content_type: string;
  title: string;
  description: string | null;
  published_at: string | null;
  duration_seconds: number | null;
  canonical_url: string;
  cover_url: string | null;
  language: string | null;
  status: string;
  metadata: Record<string, unknown>;
  first_seen_at: string;
  last_seen_at: string;
  source_kind: SourceKind;
  source_provider: string;
  fetched_at: string;
  source_url: string | null;
  created_at: string;
  updated_at: string;
  tags: string[];
  latest_snapshot: ContentSnapshot | null;
  view_growth_24h: number | null;
  media: ContentMedia | null;
  artifacts?: MediaArtifactRecord[];
}

export interface MediaArtifactRecord {
  id: string;
  content_item_id: string | null;
  download_id: string | null;
  artifact_kind: string;
  language: string | null;
  format: string | null;
  file_name: string;
  relative_path: string;
  status: "pending" | "ready" | "missing" | "corrupt" | "failed" | "stale";
  size_bytes: number | null;
  sha256: string | null;
  mime_type: string | null;
  source_kind: SourceKind;
  source_provider: string;
  checked_at: string | null;
  error_detail: string | null;
}

/** Local media archived during a sync (thumbnail / video / subtitles / info-json). */
export interface ContentMedia {
  base: string;
  thumbnail?: string | null;
  video?: string | null;
  info_json?: string | null;
  subtitles?: {
    lang: string;
    file: string;
    source?: "platform" | "asr" | "local_translation" | string;
    word_timed?: boolean;
    source_language?: string;
    model?: string;
  }[] | null;
  subtitle_artifacts?: { lang?: string; file: string; kind?: string; source?: string }[] | null;
  subtitle_exports?: {
    lang: string;
    file: string;
    format?: string;
    bilingual?: boolean;
    show_timestamps?: boolean;
  }[] | null;
  subtitle_show_timestamps?: boolean;
}

export interface ContentRecordPage {
  items: ContentRecord[];
  page: number;
  page_size: number;
  total: number;
}

export type PublicationStatus =
  | "planned"
  | "scheduled"
  | "published"
  | "unverified"
  | "failed"
  | "cancelled";
export type PublicationWindowKey = "1h" | "3h" | "6h" | "24h" | "72h" | "7d" | "30d";
export type AttributionMeasurementStatus = "measured" | "not_due" | "unavailable";

export interface PerformanceAttributionRecord {
  id: string;
  publication_id: string;
  window_key: PublicationWindowKey;
  window_seconds: number;
  target_at: string;
  measurement_status: AttributionMeasurementStatus;
  captured_at: string | null;
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  share_count: number | null;
  favorite_count: number | null;
  follower_gain: number | null;
  average_watch_time: number | null;
  completion_rate: number | null;
  source_kind: SourceKind | null;
  source_provider: string | null;
  source_url: string | null;
  note: string | null;
  evidence: Record<string, unknown>;
  captured_offset_seconds: number | null;
}

export interface PublicationRecord {
  id: string;
  workspace_id: string;
  created_by: string;
  generation_run_id: string | null;
  editorial_item_id: string | null;
  content_item_id: string | null;
  account_id: string | null;
  platform_id: string | null;
  title: string;
  canonical_url: string | null;
  external_id: string | null;
  status: PublicationStatus;
  scheduled_at: string | null;
  published_at: string | null;
  source_kind: SourceKind;
  source_provider: string;
  source_url: string | null;
  verification_note: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface PublicationDetail extends PublicationRecord {
  attributions: PerformanceAttributionRecord[];
}

export interface PublicationPage {
  items: PublicationRecord[];
  page: number;
  page_size: number;
  total: number;
}

export interface AttributionRefreshResponse {
  publication: PublicationRecord;
  attributions: PerformanceAttributionRecord[];
  measured_count: number;
  unavailable_count: number;
  not_due_count: number;
}

/** A platform comment on a content item (hot-comment collection). */
export interface CommentRecord {
  id: string;
  content_item_id: string;
  platform_comment_id: string;
  author_name: string;
  text: string;
  like_count: number | null;
  reply_count: number | null;
  published_at: string | null;
  fetched_at: string;
}

export interface ContentCalendarBucket {
  date: string;
  count: number;
  total_views: number;
  total_likes: number;
}

export interface ContentCalendarResponse {
  year: number;
  month: number;
  platform: string | null;
  account: string | null;
  buckets: ContentCalendarBucket[];
  total_count: number;
  total_views: number;
}

export interface ContentSnapshotPage {
  items: ContentSnapshot[];
  page: number;
  page_size: number;
  total: number;
}

export interface DerivedMetricRecord {
  id: string;
  entity_type: "account" | "content_item";
  entity_id: string;
  metric_key: string;
  window: string;
  value: number;
  calculated_at: string;
  metadata: Record<string, unknown>;
}

export interface DerivedMetricPage {
  items: DerivedMetricRecord[];
  page: number;
  page_size: number;
  total: number;
}

export interface NewsSourceRecord {
  id: string;
  workspace_id: string;
  name: string;
  source_type: "rss" | "atom" | "json" | "web" | "manual";
  url: string | null;
  category: string;
  language: string | null;
  country: string | null;
  reliability_score: number;
  priority: number;
  enabled: boolean;
  provider_key: string;
  last_attempt_at: string | null;
  last_synced_at: string | null;
  next_sync_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  consecutive_failures: number;
  active_sync_run_id: string | null;
  active_sync_status: "queued" | "running" | null;
  created_at: string;
  updated_at: string;
}

export interface ArticleRecord {
  id: string;
  workspace_id: string;
  source_id: string;
  source: NewsSourceRecord;
  external_id: string;
  canonical_url: string;
  title: string;
  summary: string | null;
  content: string | null;
  author: string | null;
  published_at: string | null;
  event_time: string | null;
  fetched_at: string;
  language: string | null;
  sport: string | null;
  league: string | null;
  country: string | null;
  metadata: Record<string, unknown>;
  duplicate_group_id: string | null;
  is_duplicate: boolean;
  is_bookmarked: boolean;
  source_kind: "live" | "imported";
  source_provider: string;
  source_url: string;
  event_id: string | null;
  heat_score: number | null;
  created_at: string;
  updated_at: string;
}

export interface ArticleRecordPage {
  items: ArticleRecord[];
  page: number;
  page_size: number;
  total: number;
}

export interface TopicEventRecord {
  id: string;
  workspace_id: string;
  title: string;
  normalized_title: string;
  summary: string | null;
  sport: string | null;
  league: string | null;
  start_time: string | null;
  last_update_time: string;
  article_count: number;
  source_count: number;
  heat_score: number;
  reliability_score: number;
  controversy_score: number;
  visual_score: number;
  story_score: number;
  status: "active" | "developing" | "closed";
  metadata: Record<string, unknown>;
  is_bookmarked: boolean;
  bookmarked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TopicEventDetail extends TopicEventRecord {
  articles: ArticleRecord[];
}

export interface TopicEventPage {
  items: TopicEventRecord[];
  page: number;
  page_size: number;
  total: number;
}

export type AutomationEntityType =
  | "content"
  | "account"
  | "news"
  | "topic_event";
export type AutomationActionType =
  | "notification"
  | "webhook"
  | "create_topic"
  | "create_generation"
  | "save_content"
  | "external_api";

export interface AutomationActionRecord {
  id: string;
  rule_id: string;
  action_type: AutomationActionType;
  config: Record<string, unknown>;
  sort_order: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AutomationRuleRecord {
  id: string;
  created_by: string;
  name: string;
  description: string | null;
  entity_type: AutomationEntityType;
  trigger_type: string;
  condition_tree: Record<string, unknown>;
  schedule: Record<string, unknown>;
  cooldown_seconds: number;
  deduplication_window: number;
  enabled: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
}

export interface AutomationRuleDetail extends AutomationRuleRecord {
  actions: AutomationActionRecord[];
}

export interface AutomationRulePage {
  items: AutomationRuleRecord[];
  page: number;
  page_size: number;
  total: number;
}

export interface AutomationEvaluationRecord {
  id: string;
  rule_id: string;
  entity_type: string;
  entity_id: string;
  evaluated_at: string;
  matched: boolean;
  condition_result: Record<string, unknown>;
  deduplication_key: string;
  event_key: string;
  execution_status: string;
  metadata: Record<string, unknown>;
}

export interface AutomationEvaluationPage {
  items: AutomationEvaluationRecord[];
  page: number;
  page_size: number;
  total: number;
}

export type NotificationProviderKey =
  | "mock_notification"
  | "email"
  | "generic_webhook"
  | "telegram"
  | "discord"
  | "feishu"
  | "dingtalk"
  | "wecom";

export interface NotificationProviderDescriptor {
  key: NotificationProviderKey;
  name: string;
  is_mock: boolean;
  config_fields: ConfigFieldDescriptor[];
}

export interface ConfigFieldDescriptor {
  key: string;
  label: string;
  value_type:
    | "text"
    | "password"
    | "number"
    | "boolean"
    | "select"
    | "json"
    | "list";
  required: boolean;
  secret: boolean;
  default: unknown;
  minimum: number | null;
  maximum: number | null;
  step: number | null;
  options: Array<{ value: string; label: string }>;
  placeholder: string | null;
  help_text: string | null;
}

export interface NotificationChannelRecord {
  id: string;
  provider_key: NotificationProviderKey;
  name: string;
  config_masked: Record<string, unknown>;
  enabled: boolean;
  last_tested_at: string | null;
  health_status: "unknown" | "healthy" | "degraded" | "unhealthy";
  created_at: string;
  updated_at: string;
}

export interface NotificationDeliveryRecord {
  id: string;
  channel_id: string;
  rule_id: string | null;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  status: "queued" | "sending" | "delivered" | "failed" | "cancelled";
  attempts: number;
  sent_at: string | null;
  error: Record<string, unknown> | null;
  provider_message_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationDeliveryPage {
  items: NotificationDeliveryRecord[];
  page: number;
  page_size: number;
  total: number;
}

export interface InboxReadStateRecord {
  item_key: string;
  item_kind:
    | "task"
    | "notification"
    | "editorial_comment"
    | "subscription_event"
    | "dead_letter";
  item_id: string;
  read_at: string;
}

export interface InboxQueueStateRecord {
  item_key: string;
  item_kind:
    | "task"
    | "notification"
    | "editorial_comment"
    | "subscription_event"
    | "dead_letter";
  item_id: string;
  state: "open" | "in_progress" | "completed";
  labels: string[];
  assignee_id: string | null;
  due_at: string | null;
  updated_by: string | null;
  updated_at: string;
}

export interface InboxExtendedItemRecord {
  item_key: string;
  item_kind: "editorial_comment" | "subscription_event" | "dead_letter";
  item_id: string;
  title: string;
  detail: string;
  status: string;
  timestamp: string;
  href: string;
}

export interface InboxSlaItemRecord {
  item_key: string;
  item_kind:
    | "task"
    | "notification"
    | "editorial_comment"
    | "subscription_event"
    | "dead_letter";
  item_id: string;
  state: "open" | "in_progress" | "completed";
  sla_status: "overdue" | "due_soon" | "on_track" | "completed";
  due_at: string;
  minutes_to_due: number;
  labels: string[];
  assignee_id: string | null;
  updated_at: string;
}

export interface InboxSlaSummaryRecord {
  as_of: string;
  window_minutes: number;
  overdue_count: number;
  due_soon_count: number;
  on_track_count: number;
  completed_count: number;
  items: InboxSlaItemRecord[];
}

export interface InboxSavedViewRecord {
  id: string;
  workspace_id: string;
  created_by: string;
  name: string;
  filters: Record<string, unknown>;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface SyncRunRecord {
  id: string;
  workspace_id: string;
  target_type: string;
  target_id: string;
  adapter_key: string;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  records_created: number;
  records_updated: number;
  progress_percent: number;
  progress_stage: string;
  progress_message: string | null;
  items_processed: number;
  items_total: number | null;
  error_code: string | null;
  error_message: string | null;
  error_detail: string | null;
  error_hint: string | null;
  metadata: Record<string, unknown>;
}

export interface SyncRunPage {
  items: SyncRunRecord[];
  page: number;
  page_size: number;
  total: number;
}

export type SyncRunEventLevel = "info" | "warn" | "error";
export type SyncRunEventType =
  | "stage"
  | "page"
  | "item"
  | "analytics"
  | "external_call"
  | "warning"
  | "error"
  | "info"
  | "summary";

export interface SyncRunEvent {
  id: string;
  sync_run_id: string;
  sequence: number;
  created_at: string;
  event_type: SyncRunEventType;
  level: SyncRunEventLevel;
  message: string;
  payload: Record<string, unknown>;
}

export interface SyncRunDetail {
  run: SyncRunRecord;
  events: SyncRunEvent[];
}

export interface SavedTopicRecord {
  id: string;
  created_by: string;
  title: string;
  summary: string | null;
  source_type: "content" | "article" | "event" | "manual";
  source_id: string | null;
  status: "inbox" | "planned" | "in_progress" | "completed" | "archived";
  priority: number;
  notes: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SavedTopicPage {
  items: SavedTopicRecord[];
  page: number;
  page_size: number;
  total: number;
}

export interface OperationTaskRecord {
  id: string;
  category: string;
  task_type: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  error_detail: string | null;
  error_hint: string | null;
  metadata: Record<string, unknown>;
}
export interface OperationTaskPage {
  items: OperationTaskRecord[];
  page: number;
  page_size: number;
  total: number;
}

export interface SystemEventRecord {
  id: string;
  severity: string;
  category: string;
  event_type: string;
  message: string;
  resource_type: string | null;
  resource_id: string | null;
  status: string;
  error_code: string | null;
  error_detail: string | null;
  error_hint: string | null;
  metadata: Record<string, unknown>;
  trace_id: string;
  created_at: string;
}
export interface SystemEventPage {
  items: SystemEventRecord[];
  page: number;
  page_size: number;
  total: number;
}

export interface AuditEntryRecord {
  id: string;
  actor_type: string;
  actor_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  change_summary: Record<string, unknown>;
  reason: string | null;
  status: string;
  error_code: string | null;
  error_detail: string | null;
  error_hint: string | null;
  trace_id: string;
  created_at: string;
}
export interface AuditEntryPage {
  items: AuditEntryRecord[];
  page: number;
  page_size: number;
  total: number;
}
