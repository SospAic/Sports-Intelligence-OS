# 平台采集、凭证与监控任务

更新日期：2026-07-29

## 1. 条件使用关系

每个字段和平台都必须单独判定，不能因为某个平台有一种可用方式，就默认允许采集该平台的全部字段。

```text
需要某项数据
  ├─ 官方 API/OAuth 是否提供且当前授权范围足够？
  │    └─ 是：必须使用 api Provider
  ├─ 是否存在官方 RSS、导出报表或已获准接口？
  │    └─ 是：使用对应 Provider，保留来源与导入记录
  ├─ 是否为无需登录的公开页面？
  │    └─ 同时确认公开访问、条款/许可、robots/许可、字段必要性、
  │       频率和限流后，才使用 public_page Playwright 抽样
  ├─ 是否为用户拥有或明确授权的账号后台？
  │    ├─ 可自动登录：使用 authorized_login
  │    └─ 已有授权会话：使用 authorized_session/storage_state_json
  └─ 均不满足：停止自动采集并记录能力缺口；可以新增经过单独审查的
       Provider，但不得绕过验证码、2FA、登录安全、访问控制或平台限制
```

优先级不是回退猜测，而是能力选择：官方接口能提供的字段不会改用浏览器；浏览器模式只补官方接口确实不提供或当前授权不足的必要字段。系统不会把抓取时间伪装成发布时间，也不会把派生分数标成平台原始指标。

## 2. 四种可选采集模式

| 模式 | 适用范围 | 凭证与限制 |
| --- | --- | --- |
| `api` | 官方 API/OAuth | Key/Token 加密保存；权限不足时明确失败 |
| `public_page` | 经确认可采集的无需登录公开页 | 必须保存合规确认、频率、页数/条数限制与来源 URL |
| `authorized_login` | 用户拥有或明确授权账号的自动登录 | 用户名/密码加密；仅适用于适配器明确支持的常规登录；遇验证码/2FA立即停止 |
| `authorized_session` | 用户在 Docker 内置可视化 Chromium 或普通浏览器中人工登录后捕获的授权会话 | 默认 CDP 为 Compose 内部 `browser:9222`；也允许本机/ Docker 主机网关；`storage_state_json` 与 Netscape Cookie 加密、隔离、永不回显；校验平台 Cookie 与过期时间 |

同一平台可以保存多类配置，切换当前模式不会删除其他模式的配置。设置页提供“一键撤销登录授权”：清除用户名、密码、`storage_state_json`、Netscape Cookie、会话过期时间和登录确认字段，保留 API 与公开页配置，并自动回退到仍然有效的安全模式。人工登录捕获方案不回传密码或 Cookie；`storage_state_json` 导入仍可继续使用。

历史账号 `metadata.adapter_config` 会迁移到加密的平台凭证表，迁移成功后删除明文；API、日志和前端只返回 `configured_fields`，不回显秘密。

## 3. 当前 Adapter 边界

| 平台 | 官方模式 | 浏览器模式 | 当前边界 |
| --- | --- | --- | --- |
| YouTube | Data API v3 | 公开页/授权登录 | 官方 API 获取频道、公开视频和公开统计；Analytics OAuth 私有指标未实现 |
| TikTok | Display API v2 | 公开页/授权登录/授权会话 | Display API 只访问 Token 所属用户；任意公开账号不伪装成 Research API，需另获 Research API 审批或使用合规公开页模式 |
| 抖音 | 开放平台 API | 公开页/授权登录/授权会话 | Token 权限不足、响应契约异常和登录墙均记录真实错误 |
| Bilibili | 当前无可依赖的官方开放数据 API | 公开页/授权登录/授权会话 | 仅通过已确认的公开页或授权账号浏览器上下文采样，不再把未文档化 WBI 接口标为官方实时 Provider |
| Mock | 无 | 无 | 只用于测试，固定 `source_kind=mock`，绝不参与真实验收 |

TikTok 当前官方实现使用 Display API v2：`GET /v2/user/info/`、`POST /v2/video/list/` 和 `POST /v2/video/query/`。它不具备按任意用户名读取公开账号的能力。

## 4. 同步、来源和错误

平台差异位于 `apps/api/app/adapters/platforms/`，业务服务只依赖统一 DTO、能力声明和错误分类。`sync_runs` 保存 Adapter、排队/开始/结束时间、状态、创建/更新计数、错误码、错误摘要、请求 ID 与元数据；同一账号活动任务幂等复用。

外部实体至少保存：

- `source_kind`：`live`、`imported` 或 `mock`；
- `source_provider`/`provider` 与 `external_id`；
- `source_url`、`fetched_at`/`observed_at`；
- 适用时保存原始响应引用、访问模式和派生指标算法。

认证失败、权限不足、登录墙、验证码/2FA、限流、超时、契约错误与未实现能力分别记录，不自动切换成 Mock。新快照缺少封面时保留上一次有效封面；前端会升级 Bilibili 图片 HTTPS 并禁止 Referer，最终加载失败则完全移除图片，不保留空白占位。

## 5. 趋势中心的数据关系

趋势中心只读取最近 24 小时且 `source_kind=live` 的观测：

1. 已配置平台 Provider 产生真实账号和作品样本；
2. 作品的播放、点赞、评论等平台字段原样保存；
3. 系统从真实标题/描述中提取受控体育词和明确 Hashtag；
4. 话题热度、关键词热度和高潜分均标记 `metric_kind=derived`，并保存算法名、样本量与来源实体；
5. 旧的未验证趋势记录迁移为 `imported/legacy_unverified`，不进入当前趋势看板。

页面中的“视频样本”是样本总数，“高潜视频”按当前平台样本内播放量百分位排序，不表示平台官方认定的爆款。

### TikTok 公开评论

公开 TikTok 作品评论优先通过浏览器请求上下文读取 `api/comment/list` 的真实响应。作品页文档加载失败并不等于评论接口不可用；只有公开评论接口没有结果时，且工作区确实配置了 Cookie，才允许一次 yt-dlp Cookie 后备尝试。评论文本、作者、发布时间、点赞数和回复数均原样保存并标记 `source_provider=tiktok_browser_comments`；无结果时显示条件说明，不填充估算值。

## 6. 调度与验证

账号同步由 Celery Worker 执行，Beat 扫描到期账号；外部调用具备超时、有限重试、退避、限流与结构化错误。真实数据验收使用：

```powershell
docker compose ps
docker compose exec -T api python /workspace/scripts/real_data_acceptance.py
```

验收脚本读取 `SIO_ACCEPTANCE_*` 或 bootstrap 登录变量，不打印凭证；检查认证 API、真实新闻、活动账号同步、趋势采集、来源标记和仪表盘统计。实际结果与环境限制见 [REAL_DATA_ACCEPTANCE.md](REAL_DATA_ACCEPTANCE.md)。

## 7. 抓取速度：快速通道

早期实现对整个窗口只发一次 `yt-dlp --dump-json`。这一次调用会为窗口里**每一个**作品完整解析播放页，且严格串行，所以耗时随窗口线性增长（20 条约 60 秒），远慢于人工使用独立下载器的体感。实测确认瓶颈不在进程启动（单次仅 693ms），而在串行的逐条完整解析。

现在 yt-dlp 适配器改为两段式：

1. **廉价枚举** —— `--flat-playlist` 先取回目录（id、标题、播放量），不解析播放页；
2. **并发详情** —— 只对真正需要完整数据的作品发起 `--dump-json --no-playlist`，用信号量并发执行。

配合两项跳过策略：已入库且策略不刷新的作品不再重复解析（`skip_known`）；增量同步首页缩小探测窗口，若整页都是已知作品则提前结束翻页，避免为了拿两条新作品而枚举整本目录。

真实账号实测（YouTube `@NBA`，窗口 20 条）：

| 场景 | 耗时 | 相对基线 |
| --- | --- | --- |
| 旧的单次全量解析 | 65.7s | 1.0× |
| 快速通道 · 全新账号 | 30.7s | 2.1× |
| 快速通道 · 增量（18 条已知） | 18.3s | 3.6× |
| 快速通道 · 稳态（全部已知） | 13.2s | 5.0× |

稳态耗时已与手工执行 `yt-dlp --flat-playlist`（11–14s）持平，且新作品的描述、发布时间、点赞数等字段零损失。

复现基准：

```powershell
docker compose exec -T api sh -lc "cd /workspace/apps/api && python scripts/bench_sync_speed.py --handle @NBA --count 20"
```

相关配置（`Settings`）：

- `sync_fast_list_enabled`（默认 `true`）—— 快速通道总开关，关闭后回退旧路径；
- `sync_fetch_concurrency`（默认 `4`）—— 详情抓取并发度，按平台再做上限钳制（YouTube 8 / Bilibili 4 / TikTok 2 / 抖音 2），风控更严的平台不会被拉高；
- `sync_incremental_probe_size`（默认 `15`）—— 增量同步首页探测窗口。
- `sync_page_limit`（默认 `40`）—— 单轮允许读取的目录页数上限；TikTok
  公开目录每页通常只有 15 条，因此不能用 5 页作为“完整目录”上限。实际运行
  仍受单轮时间预算、`max_contents` 和增量已知作品边界约束，稳态同步不会重复
  重抓全部历史作品。

**数据完整性保护**：仅凭目录读到的行（详情抓取失败，或已入库而被跳过）会被标记 `metadata.partial`。刷新策略下这类行只填补空缺字段，绝不覆盖此前完整解析已存下的描述与发布时间——否则一次详情抓取失败就会静默抹掉正确数据。

## 8. 抓取效率：登录墙必须快速失败

速度优化只解决“成功路径要多快”，失败路径同样吃时间。此前一个登录墙账号（未登录态的 TikTok 主页）实测耗时 **2m53s** 且必然失败：适配器把“公开页没返回资料”当成解析抖动抛出可重试错误，Celery 于是把整轮同步重跑 3 次。

现在的规则是：**结果注定不会变的失败，一次都不多跑。**

- **浏览器适配器**：YouTube / TikTok / 抖音 / Bilibili 四个平台的 `resolve_account`、`fetch_account_analytics`、`list_contents`、`fetch_content` 四条抓取路径，导航后一律调用 `_check_login_required(page, ...)`（URL 重定向 + 登录浮层双重探测）；反爬导致的“公开页无数据”直接抛 `LoginRequiredError` 而不是 `TransientAdapterError`。
- **yt-dlp 适配器**：stderr 命中永久错误标记时，按成因映射成三类**不可重试**异常，而不是统一的可重试错误：

  | 成因 | 典型 stderr | 异常 / 错误码 |
  | --- | --- | --- |
  | 登录墙、机器人校验、私密、会员专属 | `Sign in to confirm you're not a bot` | `LoginRequiredError` / `login_required` |
  | 地域、版权、IP 封禁、权限不足 | `not made this video available in your country` | `PermissionDeniedError` / `permission_denied` |
  | 已删除、账号封禁、404、URL 不支持 | `Video unavailable` | `AdapterNotFoundError` / `not_found` |

  真正的网络抖动（`Connection refused`、`Unable to extract webpage video data`）不在表内，仍走原有的“换解析通道重试”逻辑，可恢复场景一条不少。

- **仍保留浏览器回退**：yt-dlp 抛出上述任一错误时，适配器内部依然让浏览器适配器试一次——它带真实 profile 与 cookie，是**另一条**采集通道。分类改变的是“回退也失败之后”的行为：错误以不可重试身份逃逸，`sync.py` 走 `_terminal_error`，Celery 的 `_run_with_retry` 只认 `RetryableSyncError`，因此不再重跑。

失败账号在前端展示后端 `error_hint`，登录墙场景直接提示「需要登录凭证」并指向「设置 → 平台管理」配置登录态，而不是含糊的“平台暂时不可用”。

回归防线见 `apps/api/tests/test_login_wall_fast_fail.py`：除了 stderr 分类与“永久错误只启动一次子进程”的断言，还有 AST 级契约测试，确保四平台四条抓取路径都探测登录墙、且所有 catch-all 包装器都先 `reraise_if_terminal`——新增抓取路径时漏掉探测会直接测试失败。

## 9. 已知限制

- YouTube Analytics OAuth、私有留存/收入/流量来源尚未实现。
- 当前环境 TikTok Token 无效、YouTube 缺少 Key、抖音返回非预期响应；这些链路不能宣称真实同步成功。
- Bilibili 当前公开页触发登录墙，需配置加密自动登录凭证或有效 `storage_state_json`；系统不会绕过验证码或 2FA。
- 平台配额预算、调度随机抖动和分片队列仍待增强。
# YouTube Shorts-only channel catalogue fallback (2026-08-12)

YouTube channels without a `/videos` tab must be enumerated from the channel root URL (`/@handle`), not from `@handle/videos`. The yt-dlp adapter now switches to the root only when yt-dlp reports the deterministic `does not have a videos tab` error; timeouts and rate limits are not duplicated. The browser fallback uses the same root catalogue. A complete, unfiltered backfill records the independently observed catalogue total in the account snapshot; capped or date-filtered runs do not present their row count as the platform total.

## YouTube work-detail completeness (2026-08-12)

Fast catalogue rows are no longer treated as permanently complete when `skip_existing` is enabled. Rows marked `partial`/`flat_known`, or missing a publish timestamp, duration, or cover, re-enter the bounded detail queue. Successful detail extraction clears the stale marker. The per-video batch budget scales with the number of concurrent waves (bounded at 60 seconds), so a 49-item YouTube page is not silently cut off at the old 25-second ceiling.

When a refresh returns a new view count but omits older interaction fields, the new snapshot carries forward the last known like/comment/share/favorite values and records `carried_forward_metrics` in snapshot metadata. This keeps the UI truthful and visible without presenting an omitted value as newly observed.

## Subtitle display and YouTube downloads (2026-08-12)

The subtitle workbench and video overlay now normalize cue text to plain text: timestamps are hidden by default, cue lines are joined with spaces, and the browser wraps text according to the control width. During playback the active cue is emphasized with stronger text/background styling; the system does not fabricate word-level timings when the source does not provide them.

YouTube subtitle downloads now perform a bounded track preflight when a manual track is requested. If the requested language is available only under `automatic_captions`, the download switches to that real track and records the fallback in the task log. Empty language selectors preserve the legacy language filter instead of producing an empty `--sub-langs` value. Video format aliases such as `bestvideo+bestaudio` are normalized to valid yt-dlp selectors, and explicit output containers add a merge format.

When any download artifact is requested, the adapter also passes `--no-simulate`. This is required because yt-dlp's `--dump-json` mode otherwise returns metadata successfully while leaving video, subtitle, thumbnail, and info-json files unwritten. The behavior is covered by an offline command-construction regression test and a real Docker worker download verification.

## Subtitle multilingual translation options (2026-08-13)

The product keeps platform-provided tracks separate from machine translation: a
missing source track is never presented as if it came from YouTube/TikTok. For
local deployment, the recommended provider boundary is:

1. **CTranslate2 + NLLB-200 distilled** for broad language coverage and fast
   batch inference. NLLB covers up to 200 languages, and CTranslate2 is an
   efficient inference runtime. Verify the NLLB model license before any
   commercial deployment; the commonly used NLLB-200 checkpoints are
   non-commercial.
2. **TranslateGemma** for higher-quality common-language translation when a
   GPU/large desktop model is acceptable. It is a gated model family with
   Gemma terms and a smaller supported language set, so it is not the default
   for every-language coverage.
3. **Argos Translate** as a CPU-friendly offline fallback. It is simpler to
   deploy, but package coverage and quality vary more by language pair.

The translation provider must record `provider`, `model`, `source_lang`,
`target_lang`, `fetched_at`, and the source cue hash. It may add a translated
track, but must not overwrite the original track. Deployment should expose the
model as a separate local service or optional worker dependency so that
subtitle display/download remains responsive while translation is running.

The display path now preserves inline WebVTT word timestamps when supplied by
the source (for example, YouTube's timed `<00:...>` tags). Other tracks use cue
level emphasis until a transcription/translation provider supplies word-level
alignment; no artificial word timing is claimed as exact.

## Isolated local ASR and translation jobs (2026-08-13)

The first implementation of the local processing boundary is now in the
repository:

- `SubtitleJob` persists queued/running/succeeded/degraded/failed status,
  bounded rolling logs, result metadata and safe error details.
- `POST /api/v1/media/{content_id}/subtitle-generate` queues work and
  `GET /api/v1/media/{content_id}/subtitle-job` polls it. The content detail
  page exposes language controls and a scrollable live log.
- `app.tasks.subtitles.generate_content_subtitles` is routed to a dedicated
  `subtitle` queue. Compose starts `subtitle-worker` with concurrency `1` and
  `--max-tasks-per-child=1`; the normal account-sync worker does not consume
  that queue.
- `faster-whisper` is an optional model-backed provider with lazy model loading,
  `word_timestamps=True`, file/duration limits, and a persistent model volume.
  The default configuration remains disabled, so an unconfigured deployment
  fails fast with `asr_not_configured` instead of fabricating text.
- Existing platform tracks are reused first. A track without word timestamps
  is not upgraded by interpolating fake timings; once ASR is enabled and a
  local video exists, the worker generates a separate word-timed VTT and JSON
  timeline. Translation tracks are separate and never overwrite the original.
- Translation uses a local HTTP provider boundary compatible with a locally
  hosted Argos / NLLB-CTranslate2 / TranslateGemma service. Missing provider
  configuration produces a `degraded` job with the exact reason and keeps the
  original subtitle usable.

The Docker image installs the Python runtime (`faster-whisper`, CTranslate2,
ONNX Runtime and audio support), but model weights are not downloaded during
build. Enable ASR only after choosing a model, storage budget and CPU/GPU
capacity, then set `SIO_SUBTITLE_ASR_ENABLED=true` and
`SIO_SUBTITLE_ASR_BACKEND=faster_whisper`. Configure the local translation
endpoint separately with `SIO_SUBTITLE_TRANSLATION_BACKEND=http` and
`SIO_SUBTITLE_TRANSLATION_BASE_URL`. This prevents first-run model downloads or
translation latency from blocking account monitoring.

## Non-destructive sync updates and custom video player (2026-08-14)

Account synchronization is an additive refresh. A sparse platform response,
an empty subtitle/comment result, or a detail request that only returns a
directory row must not erase a previously stored video file, cover, subtitle
track, subtitle export, or comment. Existing media manifests are merged by
artifact filename; an observed artifact updates its metadata, while a new
artifact is appended. Existing comments are updated only with non-empty fields
and are not deleted because a ranked/top-N refresh omitted them. Deletion or
cleanup must be a separate explicit operation.

The content detail page uses a custom video player rather than the browser's
native controls. It provides keyboard shortcuts, seek buttons, volume, speed,
subtitle language and display settings, fullscreen, auto-hiding controls, and a
buffered-progress indicator. Playback time and duration are accepted only when
finite and non-negative; unknown media duration is rendered as `--:--`, and
seeking is clamped to the confirmed duration. The player preserves the
subtitle workbench's cue-level and source-provided word-level highlighting.

## LibreTranslate language-code compatibility (2026-08-14)

The bundled LibreTranslate 1.9.6 service exposes Simplified Chinese as
`zh-Hans`, while the product language value remains `zh` for UI and manifest
stability. The HTTP provider now maps `zh`, `zh-CN`, and `zh_Hans` to
`zh-Hans` on the wire. Platform tracks such as `und-auto` are sent as source
`auto`, allowing LibreTranslate to detect the source language. The provider
keeps this mapping at the integration boundary and does not rewrite stored
subtitle language values. HTTP failures now include the translation service's
response detail in the auditable job error.
