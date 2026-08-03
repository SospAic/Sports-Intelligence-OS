# 项目状态

更新时间：2026-08-02（续：全量质量门禁复跑、过期断言修复与亮/暗主题切换）

## 当前阶段

**Prompt 11 后续维护：全量审查修复、数据链路纠偏与 UX 优化**

> 本节是当前权威状态。本文后面的日期记录用于保留维护历史；若旧记录中的 WBI、默认浏览器抓取、明文 `metadata.adapter_config`、TikTok Research API、自动死信重放或趋势 Mock 种子描述与本节冲突，以本节及 `docs/PLATFORM_SYNC.md` 为准。

> **2026-08-01 续（账号监控基线升级与字段可用性渲染）**：
> - **最高优先级基线落地**：用户明确「账号 / 平台级数据，模拟浏览公开渠道能获取的必须上页；需 API / 登录授权的栏位若条件未满足，必须显式显示需要哪种条件」。据此新增 `AGENTS.md` 第 4.5 条、`docs/PROJECT_CONTEXT.md` 段落与 `docs/DATA_ACQUISITION_BASELINE.md`（字段级契约 + UI 渲染优先级 + 适配器能力边界）。基线高于内部自设限制，但不高于法律法规与平台条款。
> - **后端聚合升级（#51，已验证）**：`ContentSort` 扩展 `like_count` / `comment_count` / `share_count` / `completion_rate` / `engagement_rate`；新增 `AccountContentSummary` schema / repository 聚合（`summarize_account_contents`：完播率均值、平均观看时长、互动率、总互动、流量来源加权占比、近 24h 作品播放增量、头部作品）/ service / route `GET /accounts/{id}/content-summary`。新增契约测试 `test_account_content_summary.py`（5 passed）。Mypy、Ruff 全绿。
> - **前端字段可用性基础设施（#53，已验证）**：新增 `lib/metric-availability.ts`（字段→采集方式 / 所需条件契约与 `metricAvailability` 状态判定）、`components/metric-availability.tsx`（`AvailabilityValue` / `NeedsConditionBadge` / `TrafficSourceBreakdown` / `InteractionBreakdown`）、`lib/time-range.ts` + `components/time-range-picker.tsx`（全局复用、写 URL `range` / `from` 参数）。前端所有"需要条件"渲染均来自此单一契约，落实"数据栏位需显示需要哪种条件"。
> - **账号详情升级（#52，已验证）**：概览新增「平均完播率」「平均观看时长」「近 24h 作品播放增量」「总互动量」四张 API 依赖卡片（缺失时渲染"需要：…"徽章）+「流量来源占比」面板；作品 tab 接入 `TimeRangePicker` 与按完播 / 互动 / 点赞 / 评论 / 分享排序（服务端 `sort` + `published_from`），作品表格的完播率与主导流量列改为按契约渲染"需要条件"徽章。
> - **作品列表 / 详情升级（#55，已验证）**：作品列表接入全局 `TimeRangePicker` 并新增完播率列（可用性渲染）；单作品详情新增「互动拆解」（赞 / 评 / 藏 / 转各占播放比）、「流量来源占比」面板、平均观看时长卡，完播率与平均观看时长套用可用性渲染。
> - **验证状态**：后端 Mypy（148 源文件）、Ruff 全绿；`test_account_content_summary.py` 5 passed、`test_monitoring_api.py` 6 passed（该文件单独运行约 107s，受沙箱单命令时长限制，完整 84 项后端套件改以后台任务执行，见下方"验证状态"表）。前端 TypeScript、`ESLint`（仅 0 error / 0 warning，清理了未用导入）、Vitest 47 passed（新增 `metric-availability.test.ts` 9 项覆盖契约与预设）。所有改动仅本地提交（`codex/full-repair-real-data` 分支），不推送。

> - **延时类任务终止（红色终止按钮，#64，已验证）**：用户要求「所有延时类任务开始后按钮变为红色终止任务，样式参考行业优秀案例」。后端新增账号同步运行取消能力：`services/sync.py` 增加模块级 `cancel_sync_run` 与 `SyncService.cancel_sync_run`（幂等、释放 `lock_key`、账号置 `cancelled`、best-effort `sync_account.revoke(terminate=True)` 包裹于 try/except），并新增执行器 `_aborted(run)` 守卫在阶段边界（校验后 / 账号资料提交后 / 派生指标提交后）安全中止正在运行的同步；`models/sync.py` 与 `models/monitoring.py` 的 `sync_run_status` / `account_sync_status` CHECK 约束增加 `'cancelled'`，新增迁移 `20260801_0023_sync_run_cancelled_status.py`；`schemas/monitoring.py` 的 `AccountSyncStatus` 与 `SyncRunRead.status` Literal 同步增加 `'cancelled'`。新增两个端点：`POST /accounts/{account_id}/sync/{run_id}/cancel`（账号级）与 `POST /operations/tasks/{task_id}/cancel`（统一操作台，`category=platform_sync` 时复用同一取消逻辑，其余类别按项目"不伪造成功"红线返回 501 `unsupported_task_cancel`，而非伪装支持）。前端新增可复用两步确认 `TerminateButton` 组件（首次点击进入"确认终止？"武装态、3 秒自动复位、终止中显示旋转与"终止中…"，红色参考 Vercel / GitHub Actions / AWS 的 Stop/Cancel 行业范式），新增 `dangerButtonClass` 设计令牌；接入账号详情页头部（同步中/排队中显示红色终止）、同步进度面板、同步记录活动行，以及统一任务看板的"操作"列（`platform_sync` 活动任务显示红色终止按钮，非活动显示"—"，其他类别活动任务显示"暂不支持"）。新增契约/集成测试：`test_sync_cancel.py`（6 项，服务级取消幂等与执行器跳过）、`test_monitoring_api.py` 取消路由 3 项（含 501 路径）、`terminate-button.test.tsx`（4 项，RTL）。后端 Mypy strict、Ruff 全绿；前端 TypeScript、ESLint（0 error / 0 warning）、Vitest 全绿。

### 2026-08-02 全量质量门禁复跑、过期断言修复与亮/暗主题切换

- **全量质量门禁复跑（全绿）**：在 `codex/full-repair-real-data` 分支执行"全量测试 + 修复所有问题"完整门禁。后端：托管 venv 下 `ruff check .` 全绿、`mypy --no-incremental app` 0 错误（148 源文件）、`pytest -q` **101 passed**（本地 Docker PostgreSQL `sports_intelligence_test`）。根契约测试 **35 passed**。前端（apps/web）：`tsc --noEmit` / `eslint .` / `vitest run` **51 passed** / `next build` **39 路由 BUILD_EXIT=0** / `prettier --check .` 全绿。
- **误删 scripts/ 恢复**：整个 `scripts/`（11 文件）曾被本地误删但未提交，已 `git checkout HEAD -- scripts/` 恢复；该目录被测试/CI/Makefile/README/docs 引用，删除会破坏测试与 CI，**未提交删除**。
- **后端修复**：`editorial_rules.py` 的 `_sort_sections_parents_first` 补齐类型注解（PEP 695 泛型），消除 SQLite→PG 迁移引入的 6 个 mypy 错误；`conftest.py` 删除未用 `Path` 导入、测试库密码加 `# noqa: S105`；`test_metric_calculations.py` 排序导入。
- **契约测试修复（4 项）**：`test_infrastructure_contract.py` 的 `test_prompt_03/07/10` 与 `test_project_context.py` 的 `test_current_stage` 去掉对已删除 `providers/llm/mock.py`、不存在 `services/monitoring_seed.py` 及 `mock_llm`/`Mock Webhook` 的过期断言，改为当前真实形态（`StubLLMProvider` / `GenericWebhookProvider` / STATUS「Prompt 11 后续维护」阶段），保持"不伪造成功"契约。
- **Prettier 规范化**：新增 `apps/web/.prettierignore`（排除 `.next`/`node_modules`/`next-env.d.ts`/`pnpm-lock.yaml`）；对 apps/web 全量 `prettier --write`（约 490 个源文件，纯格式，无逻辑改动），使 `format:check` 门禁通过。
- **亮/暗主题切换（#28，已落地）**：`app/globals.css` 早已定义 `:root[data-theme="light"]` 令牌与核心表面覆盖（bg-slate-950→白、text-white/slate-100/200→深、border-slate-800/700→浅、header 白）。真正缺口是 `data-theme` 从未被设置。新增 `components/theme-toggle.tsx`（`useSyncExternalStore` 读 DOM/localStorage + 切换并持久化）、`app/layout.tsx` 注入无闪烁内联脚本（首屏前按 localStorage 设 `data-theme`）、`components/app-shell.tsx` 头部接入切换按钮。`tsc`/`eslint`/`prettier`/`next build` 均通过。
- **未完成任务核对（纠正）**：#26 前端批量操作工具栏**经核查已实现**（`app/contents/contents-client.tsx` 行多选 + 「批量创建选题」「批量添加监控规则」 + `POST /topics/batch`），任务列表陈旧，已标记 completed；#28 亮/暗主题已落地（见上）；#29 内容日历视图**现已实现**（`app/contents/content-calendar.tsx` 月历热力网格 + `GET /contents/calendar` 后端按天聚合 + `contents-client.tsx` 列表/日历切换，Playwright 实测月历渲染与当日作品列表）；#76 外部授权 P0（`docs/NEXT_TASKS.md`）仍阻塞，需用户凭证。
- 验证状态：所有改动仅本地提交（不推送，排除 `.workbuddy/`）。

### 2026-08-02（续续）：剩余任务收尾 + 平台功能全量有效数据验证

- **剩余任务收尾（按 docs/NEXT_TASKS.md 与对话确认的下一迭代项）**：
  - **P1-8 虚拟滚动（完成）**：共享 `DataTable` 增加可选 `virtualized` 模式（`@tanstack/react-virtual` 窗口化，用真实 `<tr>` 占位行保持表头对齐）；账号列表与作品列表均增加「虚拟滚动」开关（切换 pageSize=200 并启用窗口化）。
  - **P2-2 平台/账号对比（完成）**：新增 `/accounts/compare` 页面 + 客户端，选取 2–5 个账号调用既有后端 `GET /accounts/compare`（仅真实观测 live/imported，不合成），渲染粉丝/播放/互动/增量对照表与汇总卡；账号列表头部「账号对比」入口可达。
  - **P2-1 全局时间范围选择器（复核已完成）**：`TimeRangePicker` 已接入账号详情与作品列表。
  - **优化B 采集频率自适应（复核已完成）**：`sync.py` 每次成功同步后调用 `compute_adaptive_interval` 并写回 `sync_interval_seconds` + `next_sync_at`，Beat 按此错峰调度；`/accounts/{id}/sync-interval` 为按需手动覆盖。
  - **P1-1 Radix 弹窗重构（显式延后）**：属大型渐进式纯外观重构，对数据真实性无影响且一次性替换风险高，本轮未做，留作后续。
- **平台功能全量有效数据验证（硬性要求：所有功能应有有效数据）**：在 worker 容器内用真实适配器跑全平台探针。
  - ✅ **YouTube（yt-dlp）有效数据**：`Olympic Games`、channel_id `UCTl3QQTvqHFjurroKxexy2Q`、粉丝 **16,600,000**、5 条真实视频、内容分析 3/3 含真实 `view_count`(17472/11364/2458) 与 `like_count`。
  - ✅ **TikTok（yt-dlp）有效数据**：5 条视频（provider=`tiktok_ytdlp`），内容分析 3/3 含真实 `view_count`(33300/77900/14600) 与 `like_count`。
  - ⚠️ **抖音 / Bilibili（本沙箱无有效数据，代码正确）**：抖音 yt-dlp 返回 404（本就不支持）→ 浏览器兜底 0 条；Bilibili 匿名浏览器命中登录墙，适配器按项目红线正确停止（不绕过）。两者均为本环境网络/登录限制，非代码 bug；待用户配置住宅代理 + 登录态后复验。代码不伪造数据。
  - 结论：新修改的 yt-dlp 功能在 YouTube/TikTok 上满足"有效数据"硬性要求；抖音/Bilibili 受环境网络限制，已在代码层保证优雅兜底与诚实上报。
- Web 镜像重建（pnpm install + next build，27/27 静态页，`/accounts/compare` 预渲染），已 `docker compose up -d web` 部署，容器内 `/accounts/compare` 返回 200。提交 `26ce791`（未推送，排除 .workbuddy/）。

### 2026-08-02（续续续）：同步设置集中化架构反转 + 两处阻塞 Bug 修复

- **架构反转（用户明确要求）**：原先「账号级抓取设置（`accounts.max_contents_per_sync` + `accounts.adapter_config`）」与「全量重新同步按钮（`force_full`）」被推翻，改为**工作区级统一同步设置**。
  - **后端模型**：新增工作区作用域 `SyncSettings` 模型（`sync_settings` 表：id / workspace_id FK CASCADE / config JSON / 时间戳）；**删除** `Account` 上的 `max_contents_per_sync` 列、`adapter_config` 列及对应 CHECK 约束。
  - **迁移**：新增 `20260803_0002_add_sync_settings.py`（建表）、`20260803_0003_remove_account_scrape_config.py`（删 account 两列 + 约束）。
  - **Schema**：`schemas/settings.py` 新增 `YtDlpSettings`（dateafter/datebefore/playlist_start/extra_args）、`SyncSettingsConfig`（max_contents:int|None、skip_existing:bool、yt_dlp）、`SyncSettingsUpdate`、`SyncSettingsRead` 与 `DEFAULT_SYNC_SETTINGS_CONFIG`；`schemas/monitoring.py` 删除 `max_contents_per_sync`/`adapter_config`/`force_full` 与 `AccountSyncRequest`。
  - **服务/仓储**：`SettingsService` 增 `sync_settings`/`update_sync_settings`；`SyncRepository` 增 `get_sync_settings_config`（默认值合并）；`SyncService.request_account_sync` 去掉 `force_full`，`_config_for` 合并工作区全局 yt-dlp 策略（`max_items` 来自 `max_contents`），`_sync_contents` 默认**全量抓取作品**（`published_after=None`，移除增量 `newest_seen` 捷径），`max_contents`/`skip_existing` 均取自全局设置。
  - **路由**：新增 `GET /settings/sync`、`PUT /settings/sync`（owner/admin）；`POST /accounts/{id}/sync` 不再接受 `force_full` body。
  - **前端**：`shared-types` 新增 `YtDlpSettings`/`SyncSettingsConfig`/`SyncSettingsRecord`，删除账号上的抓取字段；设置页新增「同步设置」Tab（`sync-settings-panel.tsx`：max_contents、skip_existing 开关、dateafter/datebefore 日期、playlist_start、extra_args 文本域带 JSON 校验）；账号详情页**移除**「全量重新同步」按钮与「抓取设置（yt-dlp 参数）」字段集。
- **阻塞 Bug 修复（验证期发现）**：
  - **重复索引**：`SyncSettings.workspace_id` 同时有 `index=True`（自动生成 `ix_sync_settings_workspace_id`）与显式 `Index("ix_sync_settings_workspace_id", …)`，同名重复注册导致 `Base.metadata.create_all` 二次建索引失败（pytest 全模块 fixture 级 `DuplicateTable`）。已删除显式 `Index`，仅保留 `index=True` + `UniqueConstraint("workspace_id")`，与迁移 `op.create_index` 命名一致。
  - **`business_hint_for` 关键字限定**：`error_detail.business_hint_for(code, *, adapter_key=None, category=None)` 的 `adapter_key` 为仅关键字参数，但 `services/sync.py` 5 处写作 `business_hint_for(code, run.adapter_key)`（位置传参）→ 同步错误路径 `TypeError` 崩溃。已统一改为 `adapter_key=run.adapter_key`（行 236/347/467/583/607）。
  - **测试库陈 schema**：持久化测试库 `sports_intelligence_test` 因 `create_all` 不 alter 既有表而滞后（缺 `audit_entries.status` 等新列），导致 27 项非相关测试误报失败。已 `DROP DATABASE` 重建，由 `create_all` 按当前模型重建全部表。
- **验证状态**：后端 `ruff check` 全绿；关联 44 项测试全过（`test_yt_dlp_adapter` / `test_settings` / `test_monitoring_api` / `test_sync_cancel` / `test_sync_degraded_status` / `test_account_content_summary` / `test_accounts_batch_compare`）；全量后端套件后台复跑中。前端 `tsc`/`eslint` 此前已通过（Part B 改动未触及前端逻辑以外的类型）。改动仅本地、未推送，待 Docker 构建 + `alembic upgrade head` 实机验收后提交。

### 2026-08-03 yt-dlp 参数全面页面化（用户要求"把所有参数都加到页面"）

- **动机**：用户认为设置页可配的 yt-dlp 参数太少，要求先把 yt-dlp 的全部相关参数都暴露到「同步设置」Tab，由用户后续挑选启用哪些。
- **后端 Schema（`schemas/settings.py`）**：`YtDlpSettings` 在原有 `dateafter/datebefore/playlist_start/extra_args` 基础上，**新增 27 个字段**并分组：
  - 日期范围：`daterange`
  - 播放列表与数量：`playlist_items` / `playlist_reverse` / `playlist_random` / `no_playlist` / `flat_playlist`
  - 筛选与排序：`sort` / `match_filter` / `match_title` / `reject_title` / `age_limit` / `min_duration` / `max_duration` / `min_filesize` / `max_filesize`
  - 网络与限流：`proxy` / `socket_timeout` / `retries` / `fragment_retries` / `sleep_interval` / `max_sleep_interval` / `sleep_requests` / `limit_rate` / `geo_bypass` / `geo_bypass_country` / `geo_verification_proxy`
  - 提取与输出：`ignore_errors`（默认 True）/ `no_warnings`（默认 True）
  - `DEFAULT_SYNC_SETTINGS_CONFIG["yt_dlp"]` 同步补齐上述默认（空串 / null / False，布尔默认 True），保证读取端始终拿到完整键。
- **适配器（`adapters/platforms/yt_dlp.py`）**：新增 `YTDLP_FIELD_SPECS`（字段名→CLI 旗标→类型映射，排除已由执行器处理的 `dateafter/datebefore/playlist_start` 与自由 `extra_args`）+ 静态方法 `_render_structured(yt_cfg)`，把结构化字段翻译为 yt-dlp CLI 参数（bool 仅为真时输出旗标、int 输出 `--flag N`、str 非空时输出 `--flag value`）。`_run_yt_dlp` 新增 `structured` 形参，原先硬编码的 `--ignore-errors`/`--no-warnings` 改为由 `structured` 按默认值驱动（单视频抓取 `fetch_content` 显式传 `{"ignore_errors": True}` 保持原行为；`--dump-single-json` 路径保持不变）。`list_contents` 把整个 `yt_cfg` 作为 `structured` 透传给命令构建；`extra_args` 透传时跳过已结构化的键，避免重复旗标。
- **共享类型（`packages/shared-types/src/index.ts`）**：`YtDlpSettings` 接口补齐全部新字段（int 类为 `number | null`）。
- **前端（`sync-settings-panel.tsx`）**：重写为按 5 个分组（时间与日期范围 / 播放列表与数量 / 筛选与排序 / 网络与限流 / 提取与输出）渲染所有 yt-dlp 字段，含统一的字段渲染器（text/int/bool），保留 `max_contents` / `skip_existing` / `dateafter` / `datebefore` / `playlist_start` 与自由 `extra_args` JSON（兜底任意未建模参数）；`disabled` 按 `canEdit` 控制；保存时把空 int 归为 null、bool 归为布尔、字符串归为串，并回填 `dateafter/datebefore/playlist_start/extra_args`。
- **测试**：桩函数（`_bind._fake`、`_empty`×2、`_windowed`）增加 `structured` 形参以兼容新签名；新增 `test_structured_yt_dlp_params_reach_adapter`（结构化策略整包透传）、`test_render_structured_translates_fields_to_flags`（bool/int/str 翻译正确、False 不出旗标）、`test_render_structured_skips_empty_and_none`。
- **验证状态**：`ruff check` 全绿；`test_yt_dlp_adapter.py` + `test_settings.py` 共 21 passed；前端 `tsc --noEmit` 0 错误。无需新迁移（新字段仅在既有 `sync_settings.config` JSON 内，旧存储由 `DEFAULT_SYNC_SETTINGS_CONFIG` 合并补齐）。待 `docker compose build api worker beat web` + `up -d` 实机验收后提交。

### 2026-08-01 账号监控基线升级与字段可用性渲染
> - **Docker 现已安装**（本地 `Docker version 29.6.2`）。历史记录中反复出现的"本机无 Docker/Podman，无法实机验收"表述已过时；应按规定在具备 Docker Compose v2 的环境执行 `docs/FIRST_DELIVERY_REPORT.md` 的目标环境验收，仍不得把 Mock / 静态 Compose 校验描述为 PostgreSQL/Redis/真实平台成功。
> - **Bilibili 适配器声明失真**：2026-07-28 记录称"完整实现 `BilibiliAdapter`（约 779 行）"，但当前代码仅有 `apps/api/app/adapters/platforms/bilibili_browser.py`（`BilibiliBrowserAdapter`，基于 Playwright 的合规公开页抓取，匿名优先，登录墙场景失败），**不存在独立的 `bilibili.py` / `class BilibiliAdapter`**。以当前代码为准。
> - **未提交工作**：本会话（2026-08-01 收尾）在 `codex/full-repair-real-data` 分支一次性新增了优化 D（play_follower_ratio 相对指标 + 迁移 + 测试）、P1-5 新闻预览 Drawer、P1-7 全局键盘快捷键、P2-3 新闻聚类视图，连同此前 2026-08-01 维护（适配器能力端点、账号历史曲线、错误徽章及对应前端/测试）共约 160 个文件变更，已全部通过 Ruff/Mypy/Pytest(81)/tsc/ESLint/Vitest(38) 质量门禁，并以**仅本地提交、不推送**的方式保护，避免丢失；推送前仍须按 `docs/FIRST_DELIVERY_REPORT.md` 在具备 Docker Compose v2 与目标凭证的环境做 PostgreSQL/Redis 实机验收。

### 2026-08-01 全量审查修复、数据链路纠偏与 UX 优化

**构建与部署**

- 修复 `trends-client.tsx` TanStack Query v5 判别联合类型窄化为 `never` 的构建错误：topics 区域三元链转换为 `&&` 守卫模式，预提取 `refetch`/`isFetching` 变量，`hasError` 改用 `.isError` 布尔检查。Web + API 镜像重建成功，全部容器健康运行。
- 新增 Alembic 迁移 `20260801_0019_sync_run_degraded_status.py`：`sync_runs.status` CHECK 约束新增 `'degraded'` 值。

**账号监控数据链路修复（关键 Bug）**

- **根因**：YouTube 浏览器适配器返回 `"subscriber_count"` 但同步服务期望 `"follower_count"`，导致指标全为 NULL 但虚报 success。
- 修复 `youtube_browser.py` 字段映射：`subscriber_count` → `follower_count`。
- 同步服务新增数据质量验证：指标全 NULL 时状态标记为 `"degraded"`（非 success），附带消息"指标提取失败，仅更新了账号资料"。
- YouTube 浏览器适配器提取全失败时记录 warning 日志并在 metadata 中标记 `extraction_failure: true`；该约定已于 2026-08-01 补齐至 `bilibili_browser.py`/`tiktok_browser.py`/`douyin_browser.py`，四者均会在全部指标提取失败时记录 warning 并在 metadata 写入 `extraction_failure: true`（见下方"已知限制"）。
- 数据库验证：197 条 account_snapshots 中仅 89 条有 follower_count，youtube_browser 27 条全为 NULL（修复后新同步将正确写入）。

**API 后端高优先级修复**

- `generation.py`：无效 provider_key 返回 404（原为未处理 500）。
- `trends.py`：`collect_platform_trends.delay()` 添加 Redis broker 失败处理（503）。
- `models/news.py`：Article CheckConstraint 补充 `'mock'` source_kind。
- `services/sync.py`：进度报告 off-by-one 修复（移除 `+ 1`）。

**前端错误处理补全**

- `logs-client.tsx`：events/audits 查询添加 StatePanel 错误状态和重试按钮。
- `notification-channels-client.tsx`：channels 查询添加错误状态渲染。

**表格列宽与按钮换行修复**

- `data-table.tsx`：`<td>` 添加 `whitespace-nowrap`，表格 `min-w` 从 760px 提升至 1100px。
- 账号、新闻、作品、事件四个页面的操作按钮容器均添加 `whitespace-nowrap`。

**状态持久化**

- 新增 `lib/use-persisted-state.ts`：`useUrlState`（URL search params）和 `useLocalStorageState`（localStorage）。
- 趋势中心：platform/category/sort 通过 URL params 持久化。
- 新闻热点：view/source/sport 通过 URL params 持久化。
- 账号监控：platform/列可见性/密度通过 localStorage 持久化。

**P0 UX 改进**

- 新增 `Tooltip` 组件（CSS group-hover），集成到顶栏快速创建、通知中心、侧边栏折叠按钮。
- LLM 设置保存/测试按钮添加 Loader2 旋转 loading 状态。
- `StatePanel` 新增可选 `action` prop，支持空状态下展示引导操作按钮。

**LLM 设置面板增强（前轮完成，本轮验证）**

- 24 个提供商预设（国际 11 + 国内 11 + 本地/网关 2），自动检测当前配置。
- 调用模式选择器：API 直连（推荐）/ 浏览器代理（实验性）。
- 保存后立即更新 TanStack Query 缓存，无需刷新。
- Groq 更名为 "Grok (xAI)"（base_url: api.x.ai），独立保留 "Groq (LPU)" 条目。

**全量项目审查结论**

- API 后端：80+ 文件无语法错误、无断裂导入、无缺失 await。高优先级问题已修复（见上）。
- 前端：无活跃 TypeScript 类型错误，无断裂导入。4-5 个组件缺少错误状态已补全。
- 基础设施：Docker Compose 配置正确，依赖顺序正确，Celery 队列路由完整。建议项：worker/beat 添加 healthcheck、生产镜像移除 dev 依赖。

**UI/UX 评估（仅结论，未改动）**

- 综合评分 6.5-7.5/10。主要提升方向：组件工程化（Radix 替代手写弹窗）、数据表达力（缩略图/sparkline/聚类视图）、交互精细度（Tooltip/URL 持久化/批量操作）。
- 30 项改进清单按 P0-P3 排列，P0 已全部完成。
- 详细报告见工作区输出 `UI-UX-Assessment.md` 和 `Feasibility-Analysis.md`。

**运行状态**

- Docker 7 服务全部健康（postgres、redis、api、worker、beat、web、proxy）。
- API 健康检查：database ok、redis ok。
- 浏览器验证通过：趋势中心（平台卡片+视频+话题+图表）、LLM 设置（24预设+调用模式）、账号监控（进度条+状态+详情）、新闻热点（卡片网格+热度+操作）。

**已知限制与待办**

- Bilibili **仅有**浏览器适配器（`bilibili_browser.py`），因登录墙在匿名场景下失败（需配置加密 Cookie 或账号凭证；当前无独立公开 API 适配器，不存在"切换公开 API"路径）。
- TikTok 浏览器适配器间歇性失败（反爬限流，需请求间隔和 UA 轮换）。
- YouTube 已有 API Key（`youtube.py` 已实现），建议将 platform 记录 `adapter_key` 从 `youtube_browser` 切换为 `youtube`，以消除 degraded 根因。
- `extraction_failure` 元数据约定已于 2026-08-01 补齐至全部 4 个浏览器适配器（见上方正文）。
- 账号历史曲线展示（后端 `GET /accounts/{id}/metrics/history` + 前端 Recharts 面积图）、错误分类标准化（后端 `PlatformAdapterError.code` 语义码 + 前端同步错误徽章）与适配器能力声明（优化 E：后端 `GET /settings/platform-adapters` 能力矩阵 + 前端设置页「平台管理」渲染能力矩阵）已于 2026-08-01 完成。相对指标计算（优化 D）：`engagement_rate`、`account_baseline_ratio`（相对账号基线，即单条播放 / 近 30 日播放中位数）此前已实现，本轮新增 `play_follower_ratio`（播放 / 粉丝比）并通过迁移与契约测试；采集频率自适应（优化 B）仍为下一迭代。
- **分支治理**：当前 `codex/full-repair-real-data` 分支仍含大量未提交变更（含 2026-08-01 维护），须在验收前提交保护。
- 本轮未实施、诚实列为下一迭代的 UX/架构项（未以静态页面、占位或硬编码冒充完成）：**#26 批量操作工具栏、#28 亮/暗主题、#29 内容日历视图已于本分支实现（见上「未完成任务核对」），从下方移除**。剩余待下一迭代：P1-1 Radix 弹窗/对话框重构（渐进替换手写弹窗）、P1-8 虚拟滚动（依赖 `@tanstack/react-virtual`，当前前端镜像未安装，需装依赖并重建镜像）、P2-1 全局时间范围选择器（需统一各查询时间参数，疑似已接入待复核）、P2-2 平台对比模式（需后端对比聚合 API）；优化 B 采集频率自适应（按视频发布时间动态调整 Celery Beat 间隔）仍为下一迭代。

### 2026-08-02（续）：yt-dlp 全平台接入与质量门禁复绿

- **yt-dlp 全平台接入（用户「全平台尝试 yt-dlp」）**：新增 `app/adapters/platforms/yt_dlp.py`（YtDlpAdapter 基类 + YouTube/TikTok/Douyin 三适配器，key: youtube_ytdlp/tiktok_ytdlp/douyin_ytdlp），逆向各平台私有 InnerTube/web JSON，免 API Key/浏览器，返回精确播放/点赞/评论/分享、时长秒、描述全文、tags、结构化 channel_id、精确发布时间；账号/analytics 用 `--dump-single-json`（Browse API），内容列表用 `--dump-json`；yt-dlp 取不到时自动回退浏览器兜底（抖音基本不支持、TikTok 偶尔需要），不伪造数据。registry 注册三适配器；`platform_catalog_seed` 把 youtube/tiktok/douyin 默认 adapter_key 切到 yt-dlp；pyproject 加 yt-dlp 依赖；前端 `operation-labels.ts` 加中文标签；`main.py` 启动幂等 seed。修复 seed 关键 bug（先按 adapter_key 查 descriptor，避免遗留同名适配器把 adapter_key 静默改回 legacy）。离线单测 `test_yt_dlp_adapter.py` 7 passed。容器内真实验证：YouTube 账号/analytics/list/content-analytics 全经 yt-dlp 免浏览器取精确数据，TikTok list 经 yt-dlp 取精确播放量，Douyin 回退浏览器。已提交 `codex/full-repair-real-data` 分支 c808329，部署并重启 api/worker/beat，DB adapter_key 已切到 yt-dlp。
- **质量门禁复绿（收尾）**：修复若干累积 lint/类型/测试问题——`monitoring.py` 内容日历聚合 `count` 标签与 `Row.count()` 方法冲突（真实数据下会崩，已改名 `content_count`）；`browser_base.py` proxy 参数补 `ProxySettings` 类型；`base.PlatformAdapter` 增加默认 `aclose` 钩子；`yt_dlp.py` 缩略图返回 `str()` 强转；ruff 10 项（I001/UP041/S110/S105/E501）全修。ruff / mypy（149 文件）全绿；`pytest` 全绿（修复 `test_monitoring_api` 对平台列表顺序的脆弱断言为成员断言）。

---

### 2026-08-01 SQLite 数据链移除与 PostgreSQL 唯一数据链路落地

**目标**：按用户要求删除 SQLite 数据链，仅保留原计划的 PostgreSQL + Redis + Celery 正式数据链路；测试套件与数据库迁移全部改为在真实本地 Docker PostgreSQL 上验证。

**范围与结果**
- 测试套件（101 项）已全部从 SQLite（aiosqlite/sqlite）迁移到本地 Docker PostgreSQL（`sports_intelligence_test`）：conftest 改为会话级建库 + 函数级 `TRUNCATE ... RESTART IDENTITY CASCADE`（排除 `alembic_version`），所有测试使用 `postgresql+asyncpg` / `postgresql+psycopg` 连接串。
- 生产代码移除 SQLite 适配分支（`app/db/session.py`、`search.py`、`settings.py` 等）；全局搜索在 PostgreSQL 下统一使用 `to_tsvector`/`plainto_tsquery`/`ts_rank`，中文查询因默认 tsvector 不支持分词回退到 `ilike`。
- 删除废弃的 SQLite 验证脚本 `scripts/verify_sqlite_migration.py` 与孤立的 `data/local-runtime.sqlite3` 数据文件。

**迁移过程中暴露并修复的生产级 PostgreSQL Bug（SQLite 不强制外键/类型而长期被掩盖）**
- `rule_sections.parent_id` 自引用外键：批量插入须父节点先于子节点，否则 PostgreSQL 报外键违反。新增 `_sort_sections_parents_first` 拓扑排序，应用于 `_materialize_document`（导入，覆盖 txt 与 json）与 `_clone_version`（由已发布版本克隆草稿）。
- Alembic 数据迁移 `20260729_0014`：`trend_topics` 等表的 `metadata` 为 `json` 类型，原 SQL 使用 `|| jsonb_build_object(...)`（`json || jsonb` 在 PostgreSQL 无对应操作符）。已对 `metadata` 增加 `::jsonb` 强制转换（upgrade 与 downgrade 同步修复）。
- 模型/迁移漂移：模型声明了两个未被任何迁移创建的索引（`ix_notification_templates_workspace_category`、`ix_template_versions_template_status`）。新增迁移 `20260801_0024_add_notification_template_indexes.py` 补齐，使 `alembic upgrade head` 与 `Base.metadata.create_all` 产出的 schema 一致；已验证 `alembic upgrade head` 全链通过、`alembic check` 无漂移、0024/0023 可降级还原。

**验证**
- 完整后端测试套件在本地 Docker PostgreSQL 上 **101 passed, 0 failed**。
- `alembic upgrade head` 在全新 PostgreSQL 数据库上 24 个迁移全部成功，`alembic check` 报 "No new upgrade operations detected"。

### 2026-07-31 清单全量闭环、LLM 网关与 E2E 基础设施

- P0.0 前端收尾部署完成：Web 镜像重建并健康运行，平台分布只取活动账号、任务类型中文化、同步记录首屏 20 条已生效。
- LLM 接入方案落地：docker-compose 新增 New API 网关（calciumion/new-api，profile `llm`，端口 3306）和 Chat2API 实验服务（gpt4free，profile `llm-experimental`，端口 8020）；后端 SSRF 校验增加 `llm_internal_hosts_allowlist` 配置，Docker 内部网关主机名可绕过公网检查；前端 LLM 设置新增两个本地预设；文档见 `docs/LLM_GATEWAY.md`。
- P1.1 停用已确认失效的 CBS MLB RSS（404）和 ESPN Top 源；新增 BBC Sport、The Guardian Sport、Sports Illustrated 三个替换源（默认停用）。
- P1.2 新增离线重聚类工具 `scripts/recluster_articles.py`，支持 `--preview`/`--execute`/`--rollback` 三模式，需人工确认，自动备份可回滚。
- P1.3 趋势视频、话题和新闻事件新增评分解释端点（`/explain`）和前端可折叠"评分解释"面板，展示分量原值、百分位、权重、缺失字段、样本窗口和置信度。
- P1.4 新增跨平台同题聚类服务与 `cross_platform_links` 表（0017 迁移）；以实体重叠 ≥ 2 且标题相似度 ≥ 0.6 为跨语言阈值，仅生成建议链接，不自动合并；提供确认/拒绝 API。
- P2.1 新增 Playwright E2E 测试（390/768/1440 三视口）覆盖登录、键盘导航、全页截图和 axe-core 无障碍扫描；GitHub Actions `e2e.yml` 工作流在 Docker Compose 环境执行。
- P2.2 全局搜索修复 ArrowUp 环绕 bug，新增 scrollIntoView 跟随。
- P2.3 测试客户端新增 `httpx.AsyncClient` + `ASGITransport` 异步 fixture，pyproject 显式声明 httpx>=0.28 并过滤弃用警告。
- P2.4 新增可复用 `Pagination` 组件（"第 X 页 / 共 Y 页"），新闻页已集成。
- P2.5 新增 `user_view_preferences` 表（0018 迁移）和 GET/PUT API；账号列表页从服务端加载/保存视图偏好，localStorage 保留为回退缓存。

### 2026-07-31 评分可解释性抽屉与跨平台同题聚类

- **P1.3 评分可解释详情抽屉**：趋势视频（breakout_score）、趋势话题（heat_score）和新闻事件（heat_score）均新增 `GET .../explain` 端点，返回分量原值、百分位、实际权重、加权贡献、缺失字段、样本时间范围、置信度及变化原因。前端在趋势页视频卡片、话题行和事件列表各增加可折叠"解释"面板，缺失字段以琥珀色高亮，置信度以 Badge 展示。
- **P1.4 跨平台同题聚类与语言归一化**：新增 `cross_platform_links` 表和 `CrossPlatformClusterService`，以实体重叠（队伍、选手、赛事）为主要匹配信号，跨语言匹配要求实体重叠 ≥ 2 且标题相似度 ≥ 0.6。系统仅创建 `suggested` 状态的建议链接，不自动合并；需人工通过 confirm/reject 端点确认。语言检测（zh/en/mixed）和标题归一化仅用于比较，不替换原始标题。
- 新增 Alembic 迁移 `20260731_0017`；API 端点：`GET /trends/videos/{id}/explain`、`GET /trends/topics/{id}/explain`、`GET /news/events/{id}/explain`、`GET /trends/cross-platform-links`、`POST /trends/cross-platform-links/run`、`POST /trends/cross-platform-links/{id}/confirm`、`POST /trends/cross-platform-links/{id}/reject`。
- 前端新增 `components/score-explanation.tsx` 可复用组件。

### 2026-07-30 指标、可靠性、同步进度与前端全量纠偏

- 完成账号、作品、趋势和新闻全部推荐指标复核；原始值缺失保持 `null`，派生值保存公式版本、样本、字段覆盖、实际窗口、输入实体和置信度。作品高潜分、话题热度、YouTube 榜单机会分、事件客观热度均改为缺失权重重归一化，并按样本量向中性 50 收缩。完整口径见 `docs/METRIC_CATALOG.md`。
- 折线图按完整时间戳排序，同日多次观测显示时分；缺失点不再补零，最新值按时间而非接口顺序取得。Dashboard 不再把停用账号计入监控数，也不再以 `fetched_at` 冒充新闻发布时间。
- 账号同步增加排队、校验、账号资料、作品列表、指标、派生、完成/失败等阶段，保存百分比、处理数、总数和安全错误详情；详情页自动轮询并显示进度条，最近记录限制为 20 条以控制页面长度。
- 新闻源失败采用有上限的指数退避，成功后清零；平台、新闻和 LLM 外部调用进入 `external_call_attempts`，终态失败进入 `system_events`。中文搜索使用 CJK 兼容匹配，已用“世界杯”真实作品验证。
- 事件热度排除收藏对客观分的影响，重复内容只参与一次文章量评分；单来源标记未交叉验证。标题聚类加入中文双字组，实体补充不再降低强标题相似度；历史事件未自动破坏性重聚类。
- 规则编辑器首屏最多呈现 120 条规则并支持继续加载，避免一次渲染 1,021 条规则；表格增加移动横向提示、语义 caption、`aria-sort`，表单与筛选控件补齐标签。
- 页面加入克制的进入、悬停、按压、进度状态动画，支持 `prefers-reduced-motion`，粗指针控件最小 44px。无缩略图时不保留空白媒体框；来源提供真实封面时正常展示。
- 迁移 `20260730_0016` 非破坏性隔离无关联的错误页账号和 CRUD 测试新闻源；账号页默认展示“监控中”，仍可查看停用记录；隔离源可通过 `include_quarantined=true` 的 API 明确查询。
- 本地 Docker 真实验收通过：13 个鉴权 API、6 个账号任务、2 个真实 RSS 成功、2 个真实源失败、首页 100 条 `live` 新闻与 100 条 `live` 趋势作品；安全默认值在验收后恢复。API 78 项、Web 35 项、TypeScript、ESLint、Ruff、Mypy 和生产构建全部通过。

运行边界：当前 Compose 已部署全部后端、迁移和主要前端修复。最后完成的三项纯前端收尾（平台分布只取活动账号、任务类型中文化、同步记录首屏 20 条）已通过 TypeScript、ESLint 和 35 项 Web 测试，但因桌面环境提权用量上限未能再次重建 Web 镜像；下次执行 `docker compose build web` 与 `docker compose up -d web` 后生效。

未完成项和外部授权边界见 `docs/NEXT_TASKS.md`；本轮实测明细见 `docs/REAL_DATA_ACCEPTANCE.md`。

### 2026-07-29 当前实现

- 平台采集采用条件路由：`api`、`public_page`、`authorized_login`、`authorized_session`。官方 API 有足够权限时必须优先；公开页必须具备五项确认、采样频率和限流；自动登录凭证与 `storage_state_json` 加密、隔离且不回显，遇验证码/2FA停止。
- 同一平台切换模式不删除其他模式配置；“一键撤销登录授权”清除用户名、密码、授权会话和确认字段，保留 API/公开页配置并安全回退。`storage_state_json` 功能本身保留。
- TikTok 官方路径已纠正为 Display API v2，并明确仅访问 Token 所属用户；不再把 Display 与 Research API 混用。Bilibili 未文档化 WBI 趋势记录已改为 `imported/legacy_unverified`，不作为实时来源。
- 趋势中心只显示最近 24 小时 `live` 观测；真实作品派生话题、关键词与高潜分，保存算法、样本和来源实体。页面明确标注“派生热度”“视频样本”“高潜视频”，不冒充平台官方爆款指标。
- 新闻正文二次抓取改为显式 opt-in，需同时确认公开访问、条款/许可、robots/许可、字段必要性和限流；RSS 自带正文仍正常入库。Provider 注册表现在正确传递 SSRF DNS 配置。
- Outbox、死信、通知模板、全局搜索、Dashboard 聚合和全量 CRUD 保留；死信仅允许操作者手动重放/丢弃，不再自动循环重放毒事件。
- Docker 七服务健康；真实验收已通过 13 个鉴权 API、Chromium 启动、CBS Sports/Deadspin RSS、302 条真实 Bilibili 作品、302 条实时趋势视频样本和各 8 条实时派生话题/关键词。TikTok Token 无效、YouTube 缺 Key、抖音响应异常、Bilibili 登录墙如实记录为未通过。
- 前端逐页与移动端审查覆盖仪表盘、趋势、账号、作品、新闻、创作、规则、Prompt、通知模板、设置及运维页；修复缩略图 HTTPS/防盗链和失败无占位、仪表盘移动端横向溢出、趋势命名与指标语义。

详细采集关系见 `docs/PLATFORM_SYNC.md`，实测结果见 `docs/REAL_DATA_ACCEPTANCE.md`。

## Prompt 00–01 已完成

- 仓库级长期执行约束、完整产品上下文、严格阶段门禁与数据真实性红线。
- 12 份 Prompt 01 设计文档，覆盖产品、架构、领域模型、数据库、API、Adapter/Provider、规则、Prompt、通知、安全、路线图与验收。
- Identity、Monitoring、News、Editorial Knowledge、Generation、Automation、Notification、Operations 八个 Bounded Context 及相应数据/流程设计。

## Prompt 02 已完成

### 工程与运行基础

- 初始化 `apps/web`、`apps/api`、`apps/worker` 和 `packages/shared-types`、`packages/ui`、`packages/config` Monorepo；提交 pnpm 锁文件。
- Next.js 16、React 19、TypeScript、Tailwind CSS 4、TanStack Query、React Hook Form、Zod 的可构建前端基线。
- FastAPI、SQLAlchemy 2、Pydantic 2、Alembic、PostgreSQL、Redis、Celery Worker 与 Celery Beat 的独立进程入口。
- Docker Compose 编排 PostgreSQL、Redis、API、Worker、Beat、Web 和 Caddy Proxy；数据库、Redis、API 和 Web 有健康检查及依赖就绪门。
- API 启动时执行 Alembic 升级；提供 `/health/live` 和包含 PostgreSQL/Redis 探针的 `/health/ready`。
- 结构化 JSON 日志、请求 ID、统一 Problem Details 错误响应、开发/测试/生产配置校验。
- `.env.example`、`.gitignore`、`.dockerignore`、EditorConfig、Dockerfile、Caddyfile、本地 PowerShell 脚本和 GitHub Actions CI。
- `make dev/up/down/logs/migrate/seed/test/lint/format` 全部提供。

### 身份与安全

- 建立 User、Workspace、WorkspaceMembership、Session，以及 TaskRun、OutboxEvent、SystemEvent、AuditEntry 基础表与首个 Alembic 迁移。
- 密码采用 Argon2；登录使用随机不透明会话令牌，数据库只保存 SHA-256 哈希。
- 实现登录、CSRF Token、退出、当前用户 `/api/v1/me`、FastAPI 依赖保护和 Next.js 服务端管理页保护。
- Cookie 使用 HttpOnly、SameSite=Lax；生产配置强制安全 Cookie，并拒绝开发 Secret 与开发数据库密码。
- 首个管理员通过 CLI 的安全交互或环境变量初始化，同时创建 Owner 工作区成员关系和审计记录；不存在默认管理员密码，也不会打印密码。

### 工程质量

- Python：Ruff、Mypy strict、Pytest；前端：ESLint、TypeScript、Vitest、Prettier、Next.js production build。
- CI 在 PostgreSQL/Redis 服务容器上执行真实 Alembic 升级和后端测试，并独立执行前端检查、构建及 `docker compose config --quiet`。
- 增加 Prompt 02 基础设施契约与 Compose 静态校验，避免服务、健康检查、Make 目标或空 bootstrap 密码约束被意外删除。

## Prompt 03 已完成

- 实现 Platform、Account、AccountSnapshot、ContentItem、ContentSnapshot、DerivedMetric 六类实体、约束、关系和 Alembic 迁移。
- 账号、作品和指标按工作区隔离；所有外部观察值保留 `source_kind`、Provider、抓取时间和适用的来源引用。
- 账号和作品外部 ID 有工作区/平台唯一约束；快照按实体/采集时间唯一，应用层禁止更新历史快照。
- 计数、比率、发布时间、流量来源、收入等高频字段结构化；平台低频扩展进入 `metadata`。
- 支持 12 个指定派生指标键、窗口、计算时间、算法元数据和时间序列索引。
- 完成 Repository/Service 分层、工作区选择、角色校验、审计、组合筛选、分页、播放量/增长量排序及 CSV 导出与公式注入防护。
- 完成用户指定的平台、账号、作品、快照、指标 API；同步入口在 Prompt 03 返回明确 501，由 Prompt 04 接管。
- 提供幂等平台目录种子与单独的 Demo 种子；Demo 平台、账号、作品、快照和指标均显著标记 `mock`。

## Prompt 04 已完成

- 实现统一 `PlatformAdapter`、规范化账号/作品/指标 DTO、Capabilities、健康状态与配置描述。
- 完成 YouTube Data API v3 Adapter：频道解析、公开统计、上传播放列表分页、视频批量统计、增量检查点、不可访问作品保留、超时、限流、配额与错误分类。
- YouTube Analytics 私有字段统一返回不可用标记，未推算流量来源、留存、收入、搜索词、分享或收藏。
- 完成稳定可复现的 `MockPlatformAdapter`，可模拟增长与瞬时异常；所有返回均为 `source_kind=mock`、Demo 名称和无效示例域名。
- TikTok、抖音、Bilibili 提供能力与配置骨架，所有采集调用明确抛出 NotImplemented，不返回伪造平台数据。
- 新增 `sync_runs` 与账号调度/错误字段；持久化锁防止同账号重复任务，终态释放，保留请求 ID、计数和安全错误摘要。
- 完成手动同步、每分钟到期账号扫描、有限指数退避、最大重试、账号/作品快照追加和 12 类派生指标计算。
- 提供 `sync_account`、`sync_account_contents`、`sync_content_metrics`、`sync_all_due_accounts`、`calculate_derived_metrics` 命名任务及独立 `monitoring` 队列。
- `POST /accounts/{id}/sync` 返回 202；`GET /accounts/{id}/sync-runs` 及账号响应暴露最近状态、错误和下次同步时间。
- Dashboard 可查看来源、最近同步状态、错误与下一计划时间；Mock 账号显著显示“模拟数据”。
- 新增 `docs/PLATFORM_SYNC.md`，同步更新 Adapter、API、模型、README 与环境配置说明。

## Prompt 05 已完成

- 新增 Source、Article、TopicEvent、EventArticle、NewsSyncRun、NewsScoringConfig 六类实体及 0004 迁移；全部工作区隔离并具有来源、时间和查询索引。
- 完成统一 NewsProvider 与 RSS、Atom、Generic JSON Feed、Manual 四种实现；支持最新/时间范围、分页、健康检查、超时、有限重试和统一错误。
- RSS/Atom/JSON 数据固定为 `live`，手动录入固定为 `imported`；缺失发布时间保持空值，抓取时间绝不冒充发布时间。
- 完成 URL 规范化、同来源外部 ID、规范 URL、内容哈希和标题相似度基础去重；跨来源副本保留并共享重复组。
- 完成最近候选标题相似度事件聚类、事件计数、来源数、可靠度、时间范围和编辑评分聚合。
- 完成事件合并、拆分、选题收藏、新闻/事件详情、组合筛选、分页及用户指定排序。
- 热度权重、半衰期与相似度阈值进入版本化数据库配置；五项权重必须总和 100，更新创建新版本并重算事件。
- 完成来源 CRUD/停用、手动录入、202 同步、同步日志、单来源锁、定时扫描、Celery `news` 队列和有限指数退避。
- 来源配置拒绝秘密字段和直接私网目标；网络 Provider 不抓取文章链接页正文。
- 提供三个默认停用的 ESPN 官方 RSS 配置示例和一个空手动来源；种子幂等且不下载文章。
- 新增 `docs/NEWS_AGGREGATION.md`，同步更新 README、API、Adapter、数据库与状态文档。

## Prompt 06 已完成

- 新增 RuleSet、RuleSetVersion、RuleSection、Rule 四类实体及 0005 迁移；全部工作区隔离，规则类型、状态、优先级、严重性和来源状态有约束。
- 保存用户提供的完整 7.9 原文：311,594 字节、1,856 行，完整文件 SHA-256 为 `9f69ee764fc9c33217699df584bba18ecd5d584af8ada3770e5c8779f9e824d6`。
- 确定性解析文档前言、29 个 Kernel、20 个 Part、编号子章节和 195 项测试，生成 816 个章节节点和 1,021 条结构化规则；每条使用原文行号引用且标记 `source_status=full`。
- 原文没有明确给出的 Why、How、Good/Bad Example、单规则 QA、依赖或冲突不由系统虚构；缺少独立 QA 形成 826 项可见非阻断警告。
- 完成规则必填项、重复 key、无效依赖/冲突、循环依赖、启用冲突、缺失章节、未解析来源、缺少 QA 和强制规则禁用验证。
- 已发布版本不可原地修改；单条或批量编辑发布版本时自动完整复制新草稿。发布前执行阻断校验；回滚只切换当前发布版本指针，不修改历史。
- 完成规则集合/版本/树/筛选、单条编辑、批量启停、校验、发布、回滚、字段级差异和 TXT/JSON 导入导出 API；写操作均受工作区角色与 CSRF 保护。
- JSON 规则包导入验证 schema 和原文哈希；完整 TXT 导入按源文件哈希幂等，CLI 重复导入已验证不会创建重复版本。
- 完成 `/rules`、集合版本页、原文/结构化/JSON 版本页、三栏可视化编辑器、差异页和导入页；核心按钮连接真实后端 API。
- 新增 `make import-rules FILE=...`、只读 `data` Compose 挂载和 `docs/RULE_IMPORT_GUIDE.md`。

## Prompt 07 已完成

- 新增 PromptCollection、PromptVersion、GenerationWorkflow、GenerationRun、GenerationStep 五类实体及 0006 迁移；全部工作区隔离并具有发布/运行状态约束和时间索引。
- Prompt 正文、变量 Schema 和模型默认参数来自 `data/prompts` 种子并保存到数据库版本；Python 只负责严格渲染、编排和校验。
- 已发布 Prompt 不可原地修改；编辑时自动创建草稿，支持发布和回滚当前版本指针。
- 建立统一 LLM Provider 契约；实现 OpenAI 兼容 Chat Completions Provider 和明确标记测试输出的 Mock LLM。
- LLM Key 只从后端环境读取；Provider 列表和 Prompt 预览不回显 Key，预览递归脱敏敏感字段。
- 完成 Sports Short Video Full Package：Research Input、Normalize Facts、Build Timeline、Story Qualification、Apply Rules、Generate Draft、Editorial Review、QA Validation、Automatic Rewrite、Final Formatting 十步持久化流程。
- 运行固定输入哈希、规则/Prompt/Workflow、Provider、模型和参数；每一步记录状态、输入、输出、Prompt 快照、时间和安全错误。
- 实现新闻、事件、作品和用户文本输入冻结；单来源或无来源保持 `verification_incomplete`，不让 LLM 自称联网核实。
- 规则按强制性和优先级编译并记录实际使用 key；单步骤 120 条上下文上限及截断状态显式保存。
- 实现参数化 200–5000 字符 QA、单行 TTS、核实警告、最多五轮自动重写、手动重写新运行、失败重试、采用、JSON/TXT 导出。
- 完成 `/generate`、`/generations`、运行详情、`/prompts`、Prompt 编辑和 `/workflows`；核心按钮连接后端 API，运行页面显示十步状态和错误。
- 新增 `make seed-generation`、Celery `generation` 队列和 `docs/GENERATION_WORKFLOW.md`。

## Prompt 08 已完成

- 新增 AutomationRule、AutomationAction、AutomationEvaluation、AutomationRuntimeState、NotificationChannel、NotificationDelivery 六类实体及 0007 迁移；规则、求值、运行状态和通知均按工作区隔离。
- 实现结构化条件树校验与三值求值，支持 AND/OR/NOT、比较、集合、包含、正则、变化量、变化比例和连续满足；字段、树深、节点数和高风险正则均有限制。
- 实现事件幂等、时间窗去重、按实体冷却和持久化连续计数；同一事件不会重复执行，缺失字段不会误判为满足。
- 实现 notification、webhook、create_topic、create_generation、save_content 和 external_api 动作链；动作失败相互隔离，AI 生成失败后仍会排队发送原始提醒。
- 建立统一 NotificationProvider，完整提供 Email、Generic Webhook、Telegram、Discord、飞书、钉钉和企业微信实现，以及明确标记的 Mock Provider。
- 渠道配置使用 Fernet 加密，生产要求独立加密密钥；API 只返回脱敏摘要，动作配置禁止保存密码、Token、Secret 或 API Key。
- Webhook 配置与发送阶段均执行出站地址检查，不跟随重定向；外部调用具有超时、有限重试、退避、限流和安全错误分类。
- Celery Beat 每 30 秒扫描近期账号/作品快照和热点事件，每 5 秒分发已持久化通知；Worker 队列新增 `automation` 和 `notification`。
- 提供自动化 CRUD、动作、条件验证、手动求值、执行历史、Provider、通知渠道、测试通知和投递历史 API。
- 新增三个默认停用的示例自动化、`make seed-automations` 和 `docs/AUTOMATION_NOTIFICATIONS.md`；示例不会在未绑定渠道时发送。

## Prompt 09 已完成

- 建立深色优先、可切换浅色的响应式后台壳层：左侧导航、全局功能搜索、通知失败计数、同步状态、快速创建、用户/工作区菜单和移动端抽屉。
- 仪表盘并行读取账号、作品、新闻、事件、自动化、通知和任务 API，展示工作区实时计数、账号趋势、热门作品/新闻和最近任务；没有数据时保持空状态。
- 完成账号列表/详情、作品列表/详情、新闻卡片/表格/时间线、事件列表/来源时间线；筛选、分页、CSV、手动同步、详情、趋势和生成入口连接真实 API。
- 新增 0008 `saved_topics`、Repository/Service/API 和批量创建；来源工作区验证、幂等、来源元数据、状态流转和审计均已落地。自动化 `create_topic` 使用同一实体。
- 完成可视化自动化条件构建器，支持嵌套 AND/OR/NOT、全部首期操作符、字段白名单、动作排序、JSON 高级视图、后端校验、保存和执行历史。
- 完成通知 Provider 动态配置表单、加密保存、脱敏展示、启停、删除、真实测试确认与投递历史；前端不读取明文密钥。
- 新增 `/operations/tasks`、`/operations/events`、`/operations/audits` 只读 API，并完成任务、系统事件、审计和设置页面。
- 所有新增页面包含 Loading、Empty、Error/Retry、Toast、Skeleton、分页及角色禁用状态；共享表格使用 TanStack Table，趋势图使用 Recharts。
- 新增 `docs/ADMIN_DASHBOARD.md`，同步更新 API、数据库、README 和阶段状态。

## Prompt 10 已完成

- 后端测试覆盖登录、平台目录/账号、YouTube 与 Mock Adapter、两次增量同步、作品/快照去重、派生增长指标、RSS、新闻去重/聚类、规则/Prompt 版本、十步生成、重写上限、条件树、冷却/去重、Webhook 映射和角色/工作区权限。
- 新增完整 Mock 垂直链路：账号同步两次 → 两份作品快照 → `view_growth_1h=125000` → 自动化命中 → 创建选题 → 同步执行 Mock LLM 十步内容包 → 建立并发送 Mock 通知 → 保存同步、生成、求值和投递记录。
- 前端测试覆盖登录、账号列表查询、账号详情路径、作品排序、新闻筛选、规则编辑、Prompt 编辑、嵌套自动化条件、通知渠道测试确认和生成 Prompt 预览。
- 修复增量同步无时区数据库值与 UTC 比较失败，以及通知模板事实包含 `entity_id` 时重复关键字导致动作失败的问题；两者均由新增集成测试回归保护。
- 修正 Makefile 中 API 容器的 Alembic、Pytest、Ruff 和 Mypy 工作目录，确保命令在实际镜像的 `/workspace/apps/api` 执行。
- 新增安装、开发、部署、平台/新闻/LLM/通知扩展、自动化和故障排查文档，以及可认证的本地 Compose 烟雾测试脚本。
- 本机没有 Docker/Podman/Make，因此不能声称已执行 `docker compose up -d` 或 PostgreSQL/Redis/Worker/Beat 实机验收；静态 Compose 契约和底层质量命令通过，完整容器验收仍需 Docker 环境留证。

## Prompt 11 已完成

- 完成架构、安全、数据正确性、后台任务、AI 工作流和 UI/API 数据链路审查，问题清单见 `docs/FINAL_CODE_REVIEW.md`。
- 新闻 RSS/JSON 与 Webhook 在真实请求前解析全部地址并拒绝非公网目标；新闻源同时拒绝 URL 明文凭证和敏感查询参数。
- 派生指标缺少历史样本时不再写零速度/零加速度，30 天播放中位数只统计 30 天内发布作品；不完整爆款评分记录缺失组件。
- 自动化正则拒绝灾难性回溯结构；7.9 QA 支持受保护答案词的提前泄露和缺失检测，并进入有限自动重写。
- Celery 增加软/硬时限、Worker 丢失重投和 2,100 秒执行租约；账号/新闻同步锁、通知发送和生成运行具备失联恢复或失败记录。
- Next.js 生产构建和本地 HTTP 冒烟通过：FastAPI `/health/live` 与 Next `/login` 返回 200；浏览器控制运行时被 Windows 沙箱阻断，因此没有把组件测试冒充可视化点击验收。
- 创建 `docs/FIRST_DELIVERY_REPORT.md`；真实数据、Mock 数据、未验证外部凭证和第二阶段风险均已明确列出。

### 2026-08-01 全量测试修复与下一迭代开发

- 全量静态分析与测试修复：后端 Ruff/Mypy 清零（修复 `cross_platform.py` 变量重定义、`news.py`/`news_seed.py` 长行与类型标注、`browser_news.py` 的 `B005`/`S112`），前端修复死导入、`react-hooks/set-state-in-effect` 与未转义引号；后端 79 项、前端 38 项测试全部通过。
- 优化 A（账号历史曲线）：新增 `GET /accounts/{id}/metrics/history?days=1..365` 端点（服务/仓储/路由/Schema），返回按采集时间升序的指标时间序列；前端账号详情「数据趋势」与「概览」接入该端点，支持 30/90/180/365 天切换，粉丝数/总播放量/作品数三张面积图。
- 优化 C（错误分类标准化）：确认后端 `PlatformAdapterError` 已具语义化 `.code`（authentication_error/rate_limited/not_found…）；前端新增 `lib/adapter-errors.ts` 的 `adapterErrorCodeTone` 并把账号监控的同步错误码渲染为红/黄/灰严重度徽章（含单元测试）。
- `extraction_failure` 元数据约定补齐至 `bilibili_browser.py`/`tiktok_browser.py`/`douyin_browser.py`。
- 优化 E（适配器能力声明）：各适配器已声明 `AdapterDescriptor`（`capabilities` / `config_fields` / `source_kinds` / `implementation_status`），新增后端 `GET /settings/platform-adapters` 端点（schema `AdapterDescriptorRead` + `build_adapter_descriptor_read`）将能力矩阵序列化输出；前端设置页「平台管理」标签页新增「适配器能力矩阵」面板，按平台展示能力 ✓/— 标记、实现状态与数据源，并按 `PlatformRecord.adapter_key` 标注「已接入平台」。新增后端契约测试。
- 顺带修复 `app/schemas/__init__.py` 中 `__all__` 被二次赋值覆盖、导致 monitoring 导出被丢弃的潜在缺陷（合并为单一导出清单并补入 adapters）。
- 优化 D（相对指标计算）：
  - `engagement_rate`（可观测互动率）与 `account_baseline_ratio`（相对账号基线 = 单条播放 / 近 30 日播放中位数）此前已在 `services/sync.py` 的派生指标流程中实现，分别对应可行性分析中 `engagement_rate` 与 `relative_performance`（video_views / median(last_30_videos)）两项。
  - 本轮新增 `play_follower_ratio`（`view_count / account_follower_count`，取最近一次账号快照的粉丝数作为发布时粉丝数的近似，metadata 中注明），在 `DerivedMetric` CHECK 约束（`models/monitoring.py`）与 Alembic 迁移 `20260801_0020_play_follower_ratio.py` 中登记新键；前端 `lib/metric-definitions.ts` 新增中文标签「播放 / 粉丝比」与 `×` 格式化。新增集成测试 `test_metric_calculations.py::test_play_follower_ratio_is_computed` 断言计算结果（1,250,000 / 12,500 = 100.0）。
- P1-5（新闻预览 Drawer）：`news-client.tsx` 卡片与表格操作区新增「预览」按钮，点击无需跳转即可在右侧滑出面板查看全文（`GET /news/articles/{id}`），支持遮罩点击与 Esc 关闭、`role=dialog` 可访问性。
- P1-7（全局键盘快捷键）：`app-shell.tsx` 注册全局 `keydown`——`/` 聚焦全局搜索、`?` 开关快捷键帮助弹窗、Esc 关闭弹窗/清空搜索；输入框内按键不触发；新增 `ShortcutsHelp` 对话框。
- P2-3（新闻聚类视图）：`news-client.tsx` 新增「聚合」视图，按需拉取 `GET /news/events` 并按事件聚合展示（标题、运动/联赛、热度、来源数、文章数、状态），卡片链接到事件详情页。
- 验证状态表已同步刷新（Pytest 84、Vitest 38、Mypy 150 源文件）。

### 账户监控与路由修复（2026-08-01 续，本轮）

- **修复降级同步伪造 `success`（HIGH）**：新增 Alembic 迁移 `20260801_0021_account_degraded_status.py`，`accounts.sync_status` CHECK 约束新增 `'degraded'`；`sync.py` 在指标提取降级时把 `account.sync_status` 置为真实 `degraded`，并写入 `last_sync_error_code="account_metrics_extraction_failed"`（此前一律伪装成 `success`，违反"不得伪造平台真实成功"红线）。外部调用审计行 `external_call_attempts.status` 仍记 `success`（外部调用本身成功，仅下游指标缺失），避免写入非法状态。后端 `AccountSyncStatus` Literal、前端 `AccountSyncStatus` 联合类型、`SyncStatusBadge`、`operation-labels` 均补充 `degraded` 渲染为「部分同步（指标缺失）」。
- **修复 `GET /accounts/view-preferences` 返回 422（HIGH）**：`view_preferences.router` 原先注册晚于 `monitoring.router`，`/accounts/{account_id}`(UUID 参数) 抢先匹配 `/accounts/view-preferences`，把 `view-preferences` 当作 UUID 解析失败。已将 `view_preferences.router` 提前注册，新增回归测试断言该路由返回 200。
- **修复内容快照虚增 `records_created`（MEDIUM）**：`sync.py` 原先把内容快照写入也计入 `created`，导致创建数翻倍；已移除该累加，快照仅作追加式审计。
- **`DERIVED_METRIC_KEYS` 补齐 `play_follower_ratio`**：与迁移/模型/前端标签保持一致。
- 新增回归测试：`tests/test_sync_degraded_status.py`（降级→`degraded` + 成功→`success`）、`test_monitoring_api.py::test_account_view_preferences_route_is_not_shadowed_by_account_id`（替换 `/api/v1/accounts/view-preferences` 现在返回 200 而非 422）。

## 验证状态

| 验证项 | 结果 |
| --- | --- |
| 后端 Ruff | 通过，应用、测试及验证脚本无错误 |
| 后端 Mypy strict | 通过，148 个源文件无错误 |
| 后端 Pytest | 完整套件 101 passed、1 warning（后台重跑，932.70s，退出码 0）；本次新增延时任务终止相关 15 项（test_sync_cancel 6 + test_monitoring_api 取消路由 3，均随整文件运行通过） |
| 仓库与验收脚本测试 | 通过，35 项测试（含安装器、Compose 配置传播与 URL 安全回归） |
| 前端 TypeScript | 通过，3 个工作区包完成检查 |
| 前端 ESLint | 通过，0 error / 0 warning（已清理未用导入） |
| 前端 Vitest | 通过，51 项测试（新增 metric-availability 契约与 time-range 预设 9 项 + terminate-button 组件 4 项） |
| Prettier | 通过 |
| Next.js production build | 通过，静态页面生成 22/22，动态路由编译成功 |
| 本地 HTTP 冒烟 | FastAPI 健康检查与 Next 登录页均返回 200 |
| 浏览器可视化点击 | 通过本地登录后的设置中心与一键内容创作验收：素材、规则、LLM 配置和通知字段均由真实 API 驱动 |
| Alembic | 本地 Docker PostgreSQL 完成 0001 → 0024 升级（24 个迁移），并核对 52 张表；模型与迁移契约通过（`alembic check` 无漂移） |
| Compose 静态校验 | 通过，7 个服务、4 个健康检查、依赖门与数据卷符合约束 |
| `docker compose config --quiet` | 本机现已安装 Docker v29.6.2，应在目标环境执行；CI 亦配置为强制执行 |

本机也没有 `make`，因此 Make 目标通过静态契约检查；各目标所调用的底层命令已分别验证。Alembic 迁移（0001 → 0024）已在本地 Docker PostgreSQL 上 `upgrade head` 全链通过并 `alembic check` 无漂移；整套 Compose（含 Worker/Beat/Web/Caddy）启动仍建议在目标环境复核。

## 数据真实性声明

YouTube 官方 Data API Adapter 已实现，但本机没有 API Key，真实调用未验证。新闻 Provider 已实现，但自动化测试只使用本地去敏 RSS/Atom/JSON 响应；默认外部 RSS 示例保持停用，未主动下载真实新闻。Feed 文章契约标记 `live`，手动文章标记 `imported`，Mock 监控数据标记 `mock`；事件收藏形成的选题标记为 `aggregated` 派生数据，不冒充原始实时来源。7.9 原文来自用户提供的本地文件，完整哈希与副本一致；结构化数据来自确定性解析，不以生成内容补齐缺失字段。真实 OpenAI 兼容 Provider 已实现但本机没有 Key，未执行真实或可计费调用；自动化测试只使用带 `MOCK TEST OUTPUT`、`source_kind=mock` 的 Mock LLM。用户文本标记 `imported`，无独立证据时保持 `verification_incomplete`。Email、Webhook、Telegram、Discord、飞书、钉钉和企业微信 Provider 已实现，但本机无真实渠道凭证，未执行真实发送；测试通知只使用 `mock_notification` 并显式记录 Mock 回执。

## 已知限制与尚未实现

- YouTube Analytics API 的 OAuth 私有分析、Comments 和配额预算尚未实现；TikTok、抖音、Bilibili 适配器已完整实现但无真实 API 凭证验证。
- 新闻聚类首期使用标题相似度和实体增强；跨语言向量、文章修订历史、自动时间线、搜索/社交/视频热点源尚未实现。
- URL 在请求前会解析并拒绝非公网地址；生产环境仍建议使用固定出站代理、网络 ACL 和 DNS 策略形成第二道边界。
- 7.9 确定性解析保留 826 项缺少独立 QA 的警告；Why/How、示例、适用范围及规则关系只在原文明示时填充，进一步人工语义整理尚未完成。
- 规则树已支持按需加载分页；数万规则规模的虚拟滚动尚未实现。
- Research 首期只使用已持久化输入和来源，未实现通用联网搜索工具；OpenAI 兼容 Provider 已支持流式 SSE 预览，但生成工作流仍使用非流式批量调用。
- 自动化首期为 30 秒级近实时扫描，不是消息总线级实时。
- 全局搜索在 PostgreSQL 下使用 `to_tsvector` / `plainto_tsquery` / `ts_rank` 实现词干提取和相关性排序；中文查询因 PostgreSQL 默认 tsvector 不支持分词，回退到 ilike 模式匹配。超大数据量场景的 GIN 索引和分区尚未实现。
- 后端测试套件（101 项）全部运行于本地 Docker PostgreSQL 隔离数据库；前端 React 组件测试与完整 Mock 垂直链路通过；PostgreSQL/Redis 容器集成已在 Docker 环境验证通过（2026-07-28 起，2026-08-01 完成 SQLite 全量迁移后转为 PostgreSQL 唯一数据链路）。

## 阶段结论

Prompt 00–11 已按顺序完成，第一次交付代码阶段结束。下一步不是继续增加首期功能，而是在具备 Docker Compose v2 和用户测试凭证的目标环境执行 `docs/FIRST_DELIVERY_REPORT.md` 中的实机验收；仍不把 Mock 或静态 Compose 校验描述成 PostgreSQL/Redis/真实平台成功。

## 2026-07-26 本地运行与行业对标补充

- 当前 Windows 主机仍未安装 Docker/Podman、PostgreSQL、Redis、Make 和 GitHub CLI；因此不能执行完整 Compose、Worker 或 Beat 实机验收。
- 使用独立 SQLite 开发数据库完成 0001–0010 迁移，并初始化本地管理员、平台目录、显式 Demo/Mock 监控数据、停用的新闻源示例、完整 7.9 规则、默认 Prompt/工作流和停用的自动化示例。（该 SQLite 开发数据库已于 2026-08-01 随 SQLite 数据链整体移除，系统现仅使用 PostgreSQL。）
- FastAPI `/health/live`、Next `/login`、真实登录、`/api/v1/me`、Dashboard 和账号 API 均返回 200；账号响应保留 Mock 标记。Redis 缺失时 `/health/ready` 如实返回 503，未将降级开发模式描述为全栈就绪。
- 行业官方产品资料对标与第二阶段建议见 `docs/INDUSTRY_BENCHMARK_AND_OPTIMIZATION.md`。优先级是表现归因闭环、趋势异常解释、跨语言事件与事实证据、人工审批，以及 Outbox/死信/重放可靠性。
- 上传前全量检查通过：后端 45 项、前端 21 项、仓库与验收脚本 27 项测试通过；Ruff、Mypy、TypeScript、ESLint、Prettier 和 Compose 静态校验通过。验收脚本新增 HTTP(S) 同源限制，拒绝非 HTTP scheme、URL 明文凭证和跨源绝对路径。
- 浏览器验收发现并修复顶部状态误报：Web 现在读取 `/health/ready`，Redis/Worker 依赖缺失时显示“后台任务服务降级”，不会因没有排队账号就宣称“同步队列正常”；设置页也会保留 503 返回中的组件级降级详情。

## 2026-07-26 跨平台一键安装

- 新增 Windows PowerShell、Linux、macOS 与 Unix 自动分发安装入口，覆盖 Windows 10/11、Ubuntu/Debian、Fedora/RHEL，以及 Rocky/AlmaLinux 的 best-effort 兼容路径。
- 安装器在缺少运行时时使用 Docker Desktop、Docker 官方 apt/dnf 仓库或 Homebrew cask；Windows 首次许可、WSL 重启和 macOS 首次许可均保留为可见用户操作，不伪造静默成功。
- 首次安装只在 `.env` 不存在时生成 PostgreSQL、会话签名和通知加密随机值；已有 `.env` 不覆盖、不自动轮换。管理员密码省略时随机生成，仅在安装成功后显示，不写入 Git 或 `.sio` 状态文件。
- 安装闭环包括 Compose 配置校验、七服务构建启动、API readiness、Alembic 自动迁移、管理员、平台目录、完整 7.9 规则、Prompt/工作流、停用新闻源与停用自动化示例。Demo 监控数据保持显式 `--with-demo-data`/`-WithDemoData` opt-in，并标记为 Mock。
- 新增 `docs/ONE_CLICK_INSTALL.md` 与安装器契约测试；PowerShell AST、Bash 语法、34 项仓库契约、45 项后端测试、21 项前端测试及生产构建均通过。脚本只在静态语法和无副作用契约层验证，当前 Windows 主机仍没有 Docker，因此没有把宿主机 Docker 安装、PostgreSQL/Redis 容器启动描述为已实机通过。

## 2026-07-26 设置中心与安全收口

- 设置中心已拆分为部署级参数和工作区级加密配置：数据库/Redis 展示脱敏拓扑、连接池、超时、重试、任务与会话参数，并只生成不含凭证的环境变量草稿，不允许 Web API 改写宿主机 `.env`。
- 新增工作区 OpenAI 兼容 LLM 配置、默认模型与采样参数、成本、超时、重试、自定义请求头、真实连接测试和 SSRF 公网地址校验；API Key 与自定义头只在后端加密保存。手动生成、Worker 和自动化生成均读取同一生效配置。
- Email、Generic Webhook、Telegram、Discord、飞书、钉钉和企业微信 Provider 均通过统一字段描述契约驱动前端，支持各自的超时、重试、签名、提及、解析模式等参数；编辑时空白 Secret 保留旧值，显式操作才能清除。
- 登录失败限流改为数据库共享窗口，身份和客户端地址仅保存 HMAC；新增每小时会话/登录尝试清理任务。浏览器验收同时修复通知凭证表单被密码管理器误填的风险。
- 当前全量结果：后端 52 项、前端 25 项、仓库契约 35 项测试通过；Ruff、Mypy strict（120 个源文件）、TypeScript、ESLint、Prettier、Next.js 生产构建和 Compose 静态校验通过；Alembic 迁移经 PostgreSQL 验证（系统已于 2026-08-01 移除 SQLite，仅保留 PostgreSQL 数据链路）。

## 2026-07-27 7.9 完整输出包扩展

### 变更内容

**默认字符范围修正（与 7.9 原始值对齐）**
- `DEFAULT_MIN_CHARS` 从 1200 → 1180，`DEFAULT_MAX_CHARS` 从 1250 → 1220
- 影响范围：`workflows/generation.py`（常量定义）、`services/generation.py`（4 处引用）、`schemas/generation.py`（校验默认值）、`providers/llm/mock.py`（mock 输出目标长度）、前端 `generation-form.tsx`（标准版预设）
- 扩展版预设同步修正为 1250–1500（对应 7.9 原文 75–90s 档位）

**输出字段从 14 字段扩展为 7.9 完整内容包**
- `validate_final_bundle` 必需字段从 14 个扩展为 22 个（A 组 14 + B 组 8）
- 新增 B 组核心字段：`spoken_char_count`、`event_identity`、`story_format`、`central_question`、`selected_hook`、`cmssml`、`ev3`、`story_architecture`
- C 组 17 个 ambiguous 字段允许 null/缺失，后端 `final_formatting` 步骤自动 `setdefault(None)`
- `spoken_char_count` 由后端从 `len(tts_en)` 计算，不依赖 LLM，校验强一致性
- `verification_status` 从 `run.verification_status` 复制，不允许 LLM 覆盖
- `lcr_enabled` 不存在时默认 `False`，字符串 `"true"` 自动容错转换为布尔值

**Prompt 种子升级至 v2.0.0**
- `data/prompts/sports_short_video_full_package.json` 版本号 1.0.0 → 2.0.0
- `user_prompt_template` 中 `final_formatting` 指令完整列出 A/B/C 三组字段及约束
- `max_tokens` 从 2400 提升至 4096（支持完整输出包）
- 默认字符范围同步修正为 1180–1220

**Mock LLM 同步升级**
- `providers/llm/mock.py` 的 `final_bundle` 新增全部 B/C 组字段占位值
- `spoken_char_count` 占位值由后端后处理覆盖，保证与 `tts_en` 严格一致

**前端展示层扩展**
- `generation-presentation.ts`：`GenerationOutputKey` 类型拆分为 A/B/C 三组，新增 17 个 label
- `generation-detail.tsx`：新增可折叠"完整叙事包"区域，展示 B/C 组字段；CMSSML/EV3 各自有独立复制按钮；ambiguous 字段标注 ⚠
- `generation-form.tsx`：标准版预设修正为 1180–1220

**测试扩展**
- `tests/test_generation.py` 新增 5 个单元测试：默认字符范围验证、B 组完整性、`spoken_char_count` 一致性、多行 TTS 拒绝、`lcr_enabled` 类型校验
- 端对端测试新增 B 组字段存在性断言、`spoken_char_count` 与 `tts_en` 一致性断言、`lcr_enabled` 类型断言、单行 TTS 断言

### 字段来源标注

| 类型 | 说明 |
|---|---|
| `explicit` | 7.9 原文明确定义 |
| `derived` | 从多个规则推导 |
| `ambiguous` | 原文不完整，系统辅助生成，不能作为完整规则依据 |
| `product_extension` | Sports Intelligence OS 产品层扩展，不在 Part 13 顶层定义 |

### 验证状态

| 验证项 | 结果 |
|---|---|
| Ruff（5 个 Python 文件） | 全部通过 |
| TypeScript 诊断（3 个前端文件） | 无错误 |
| Python 诊断（4 个后端文件） | 无错误 |
| Pytest（本机无运行时） | 待 Docker 环境验证 |

---

## 2026-07-28 可靠性、发现与模板版本化

### 新增数据库表（0012 迁移）

新增 7 张表：`outbox_event_attempts`、`dead_letter_events`、`notification_delivery_attempts`、`external_call_attempts`、`notification_templates`、`notification_template_versions`、`dashboard_stats`。Outbox 事件逐次记录每次消费尝试（最多 5 次，指数退避），超限进入死信表保留原始载荷和最后一次错误；通知投递和外部调用也各自记录逐次尝试明细。

### 可靠性基础设施

- `OutboxService`：`consume_pending` 使用 `SELECT FOR UPDATE SKIP LOCKED` 安全并发消费，每次尝试记录状态、耗时和错误；死信支持重放（重置为 pending）和永久丢弃。
- `NotificationDeliveryAttempt` 和 `ExternalCallAttempt` 模型由 `automation.send_delivery` 在每次发送时写入，成功记录 `duration_ms` 和 `provider_message_id`，失败记录 `error_code`、`error_detail_safe` 和 `retryable` 标志。
- Celery 新增 3 个定时任务：`consume_outbox_events`（15 秒）、`process_dead_letters`（3600 秒）、`calculate_dashboard_stats`（300 秒）。

### 通知模板版本化

- `NotificationTemplateService`：完整 CRUD 加版本管理，`draft → published → archived` 生命周期，发布时归档旧版本，回滚通过复制指定版本内容创建新草稿。
- 模板渲染使用 `str.format_map` 安全替换，缺失变量保留占位符不抛异常。
- API 覆盖创建、详情、列表、更新草稿、发布、回滚、删除和版本列表共 8 个端点。

### 看板统计聚合

- `DashboardStatsService` 计算 7 类统计：账号分布、作品计数、同步状态、新闻统计、生成统计、自动化统计和通知统计。
- 使用 `(workspace_id, stat_key, period)` 唯一约束的 upsert 模式，24 小时窗口，300 秒定时刷新。

### 全局搜索与实体提取

- `SearchService` 跨 9 类实体搜索：账号、作品、文章、事件、规则、自动化规则、选题、生成运行、通知渠道；精确标题 3 分、部分标题 2 分、其他字段 1 分，结果附带 `<mark>` 高亮摘要。
- `EntityExtractionService` 纯 Python NLP 提取体育/联赛/人物/地点/比分实体（30+ 运动、50+ 联赛、60+ 地点），支持中英文。
- 新闻聚类升级为实体增强：`title_similarity * 0.7 + entity_similarity * 0.3`，算法标签更新为 `entity-enhanced-v1`。
- 文章正文抓取使用 BeautifulSoup，具备 SSRF 防护（私网地址拒绝）、10 秒超时、50KB 限制，失败优雅降级。

### 规则树懒加载

- 新增 `GET /rules/{id}/versions/{vid}/sections` 端点，按层级分页返回章节，附带 `children_count` 和 `rules_count`。
- 前端 `RuleVersionViewer` 新增"按需加载"视图模式，顶层自动加载，子节点首次展开时按需获取。

### 新增前端页面

- `/notification-templates`：模板 CRUD、版本历史、发布/回滚操作。
- `/operations/external-calls`：外部调用尝试检查，支持 provider_key/call_type/status 筛选。
- `/operations/dead-letters`：死信事件管理，支持重放和丢弃。
- 侧边栏新增"通知模板"、"调用记录"、"死信管理"三个导航入口。

### Bug 修复

- `TimestampMixin` 增加 Python 侧 `default=_utcnow`，修复仅 `server_default` 导致 ORM INSERT 不含 `created_at` 的 NOT NULL 违规。
- `get_db` 依赖增加 `await session.commit()` 和异常时 `rollback()`，修复 `flush()` 数据从未提交、请求结束后事务回滚的问题。
- 懒加载 sections 端点移除 `RuleSection` 上不存在的 `level` 和 `source_reference` 属性，改为返回 `parent_id`。
- 新增 `GET /notification-templates/{id}/versions` 路由，补全缺失的版本列表端点。

### Docker 实机验证

- 7 服务 Docker Compose 完整构建启动，API、Web、PostgreSQL、Redis 均通过健康检查。
- 16 项 API 功能测试全部通过：模板 CRUD 全流程（创建/详情/列表/发布/版本/更新草稿/回滚/删除/验证删除）、6 项可靠性端点、懒加载 sections。
- Worker 日志确认 `consume_outbox_events` 每 15 秒执行、`dispatch_queued_notifications` 每 5 秒执行，全部成功。
- Beat 调度器确认所有定时任务按预期频率触发。

---

- 创作者主流程收敛为“热门视频/新闻/事件或自定义材料 → 规则预设 → 一键生成 → 结构化成品”，不再要求选择 Prompt 版本、工作流、Provider、模型或采样参数。
- 系统可以稳定识别 7.9 规则所需输入和输出：输入侧保留素材、规则、成片长度、答案词与创作备注；输出侧固定展示事实摘要、来源、故事价值、英文 TTS、中文翻译、中英文标题、搜索词、素材词、标签、工程文件名与 QA。
- Prompt 中心已从主导航和全局搜索移除；已发布 Prompt、工作流和模型参数仍由后端作为内部编排与不可变审计依据保存，没有删除既有版本、运行记录或自动化调用能力。
- `/generate` 直接读取真实作品、新闻和事件 API 并按热度/播放量展示；空状态、失败重试和 Mock 标识均保留。`/generations` 改为内容成品库，技术步骤、Prompt/模型和 Token 信息只在成品详情的折叠审计区展示。
- 修复创作者填写的答案词未进入冻结输入的问题；现在只接收有长度和范围约束的 `answer_word`、`answer_reveal_min_ratio` 与 `creator_brief`，数据库中的来源标题和事实仍不可被请求载荷覆盖。
- 本地登录后的浏览器验收通过：主导航不再出现 Prompt 中心，四类素材入口、规则预设、一键生成状态和 Mock 警告正常，页面控制台无错误。本机没有真实 LLM Key 和 Redis，未把 Mock 生成或后台任务降级描述为真实生成成功。

## 2026-07-28 平台适配器完整实现与新闻源扩展

### 历史实现：TikTok API 适配器（已于 2026-07-29 纠正）

- 当时实现的 `TikTokAdapter` 后经审计发现混用了 Display API 与 Research API 的名称、方法和请求体；当前已纠正为 TikTok Display API v2。
- 当前使用 Bearer token，按官方契约调用 `user/info`、`video/list` 和 `video/query`；能力只覆盖 Token 所属用户。
- 能力覆盖：`PUBLIC_PROFILE`、`ACCOUNT_ANALYTICS`、`CONTENT_LIST`、`CONTENT_ANALYTICS`。
- 游标分页，最大页大小 20；超时、限流、错误分类和结构化日志。
- 配置字段：`client_key`、`client_secret`、`access_token`（必填）、`refresh_token`（可选）。

### 抖音开放平台适配器

- 完整实现 `DouyinAdapter`（约 755 行），替换原有 skeleton 占位。
- 使用 GET + `access-token` header 认证；错误码映射（10001/10002=认证、10003=权限、10005=限流、2190008=未找到）。
- 指标映射：`play_count→view_count`、`digg_count→like_count`、`forward_count→share_count`。
- 配置字段：`client_key`、`client_secret`、`access_token`（全部必填）。

### Bilibili 公开 API 适配器

- ⚠️ **校对更正（2026-08-01）**：原记录所称独立 `BilibiliAdapter`（约 779 行）在当前代码中**不存在**。Bilibili 仅由 `bilibili_browser.py`（`BilibiliBrowserAdapter`，基于 Playwright 的合规公开页匿名优先抓取，拦截 `/x/space/wbi/*` 接口）实现；无独立公开 API 适配器文件 `bilibili.py`。登录墙场景需配置加密凭证，否则同步失败（见上方校对补充）。
- 无需认证即可获取公开数据；可选 `sessdata` cookie 访问受限内容。
- 错误码映射：`0=成功`、`-101=认证`、`-403=禁止`、`-404=未找到`、`-412=限流`。
- 视频时长解析支持整数秒和 "MM:SS" 字符串两种格式。
- 账号定位支持 `space.bilibili.com` URL 和数字 mid。

### 美国体育新闻 RSS 源扩展

- 新闻种子从 3 个 ESPN 源扩展为 18 个美国知名体育新闻源。
- 新增来源：CBS Sports（5 个频道）、Yahoo Sports（3 个频道）、NBC Sports / ProFootballTalk、The Ringer、Deadspin、NFL.com、NBA.com、MLB.com。
- 所有 RSS 源默认停用，显著标记为例配置；手动录入源保持启用。
- 来源归一化从源名称自动推导：`name.split("（")[0].split(" - ")[0]`。

### Outbox 事件分发与死信自动重放

- `OutboxService._dispatch_event` 集成 Redis Pub/Sub，发布到 `sio:outbox:{event_type}` 频道；Redis 连接失败时非致命降级。
- `_process_dead_letters` 只统计待处理死信；重放或丢弃必须由操作者明确执行，避免毒事件循环和外部副作用重复。
- 平台种子脚本升级为读取适配器描述符的实际能力，更新已有记录的能力字段。

### OpenAI 兼容 Provider 流式响应

- `OpenAICompatibleProvider` 启用 `supports_streaming = True`，实现完整 SSE 流式输出。
- 使用 httpx 异步流式请求，解析 `data:` 格式的 SSE 事件，提取 `choices[0].delta.content`。
- 新增 `POST /generations/stream-preview` 端点，支持前端实时逐 token 预览 LLM 输出。
- `StreamPreviewRequest` 请求体包含 system_prompt、user_prompt、model、provider_key 和 model_params。

### 全局搜索升级为 PostgreSQL tsvector

- `SearchService` 在 PostgreSQL 下使用 `to_tsvector` / `plainto_tsquery` / `ts_rank`；中文查询因默认 tsvector 不支持分词，回退到 `ilike`。系统已不再支持 SQLite 方言。
- 9 类实体搜索全部升级为双路径实现，PostgreSQL 下支持词干提取和相关性排序。
- 搜索响应新增 `search_backend` 字段标识当前使用的后端（`tsvector` 或 `ilike`）。

### 新闻正文提取增强

- 文章正文提取升级为 readability-like 三阶段算法：
  1. 移除 junk 标签（script/style/nav/header/footer/aside/iframe/form 等）
  2. 负向 class/id 模式过滤（ads/sidebar/comments/social/widgets 等）
  3. 候选容器评分：正向 class 加分、段落数量和长度加分、高链接密度惩罚、文本长度加分
- 选择最高分容器作为正文来源，输出清理多余空行，50KB 上限。

### Docker 验证

- 7 服务全部健康运行（API、Web、Worker、Beat、PostgreSQL、Redis、Proxy）。
- 4 个平台注册并显示正确能力：Bilibili、TikTok、YouTube、Douyin。
- 18 个新闻源成功种子（17 个 RSS 停用 + 1 个手动录入启用）。
- 搜索后端确认为 tsvector。
- 12/12 回归测试通过。

---

## 2026-07-28 数据增删改查（CRUD）全量补全

### 后端新增端点

- **作品（Contents）CRUD**：`POST /contents`（201）、`PATCH /contents/{id}`、`DELETE /contents/{id}`（204）。`ContentCreate` 要求 `account_id`、`external_id`、`title`、`canonical_url`，可选 `content_type`、`description`、`published_at`、`duration_seconds`、`cover_url`、`language`、`status`；`ContentUpdate` 全部字段可选（`exclude_unset`）。来源标记为 `imported`，重复 `external_id` 返回 409。
- **新闻文章（Articles）增删改**：`POST /news/articles/manual`（201）仅限 `source_type=manual` 的源；`PATCH /news/articles/{id}` 支持标题、摘要、正文、作者、运动、联赛、国家、URL、三项评分的部分更新；`DELETE /news/articles/{id}`（204）级联清理事件-文章关联。
- **新闻源（Sources）CRUD**：`POST /news/sources`（201）、`PATCH /news/sources/{id}`、`DELETE /news/sources/{id}`（204）已在 Prompt 05 实现，本次补全前端表单。
- **账号（Accounts）删除**：`DELETE /accounts/{id}`（204）已在 Prompt 03 实现（软停用），本次补全前端入口。
- 所有写操作均受 `CsrfProtectedAuth` 保护，角色门槛：创建/编辑需 `owner`/`admin`/`editor`，删除需 `owner`/`admin`。写操作均记录审计日志。

### 前端新增表单与交互

- **作品列表页**（`contents-client.tsx`）：新增"手动添加作品"按钮和内联创建表单，关联账号下拉选择器；表格新增操作列，支持内联编辑标题和删除（角色门控）。
- **新闻列表页**（`news-client.tsx`）：新增"手动添加文章"按钮和创建表单，来源下拉仅显示 `manual` 类型源；无可手动源时提示用户先到设置页创建。
- **新闻详情页**（`news-detail-client.tsx`）：新增编辑面板（标题、摘要、正文、作者、运动、联赛、国家、URL、争议/视觉/故事评分）和删除按钮，编辑后实时刷新缓存。
- **设置页新闻源 Tab**（`settings-client.tsx`）：新增"添加新闻源"表单（名称、类型、URL、分类、语言、国家、可靠度）；每行新增编辑（内联）和删除按钮。
- **账号详情页**（`account-detail-client.tsx`）：新增"删除账号"按钮（仅 `owner`/`admin` 可见），确认后跳转回列表。

### 类型修复

- `AccountRecord.platform` 类型从 `PlatformSummary` 升级为 `PlatformRecord`，修复 `capabilities` 属性 TypeScript 编译错误。

### Docker 验证

- 7 服务全部健康运行，Web 构建通过 TypeScript 检查和 Next.js 生产构建。
- 13 项 CRUD API 功能测试通过：作品创建/更新/删除、新闻源创建/更新/删除、手动文章创建/更新/删除、账号创建/删除。
- 手动文章创建需关联 `source_type=manual` 源，非手动源返回 422 "manual article requires a manual source"，前端已做引导。

## 2026-07-28 账号同步链路修复与真实测试账号

### 历史实现：Bilibili WBI 适配器（已停用）

- 该阶段曾接入未文档化 WBI 接口；2026-07-29 审查后已从运行注册表移除。旧趋势记录改标 `imported/legacy_unverified`，当前 Bilibili 仅使用已确认公开页或授权账号浏览器模式。
- **-352 风控限流**：Bilibili 对短时间大量请求返回 -352 "风控校验失败"。将 -352 映射为可重试的 `RateLimitError`（retry_after=3s），将 HTTP 412 也映射为 `RateLimitError`（retry_after=5s），并将默认 `min_request_interval` 从 0.0 提升至 0.5 秒，`retry_base_seconds` 从 0.25 提升至 0.5 秒。
- **端到端验证**：Bilibili 咪咕体育（mid=414615582）和 NBA（mid=1744580599）两个真实公开账号同步成功。每个账号同步 150 条视频内容，账号快照包含粉丝数（~25 万 / ~41 万），内容快照包含播放、点赞、评论、分享等指标。

### TikTok 适配器修复

- **resolve_account 定位修复**：原来 `resolve_account` 忽略 `locator` 参数，始终返回 token 持有者的账号信息。修复后：先解析 locator 获取目标 username，尝试从 API 获取用户信息；若 API 返回的 username 与目标匹配则使用完整数据，否则构造最小化的 `PlatformAccountData`（`list_contents` 仍可通过 username 过滤正常工作）。`fetch_account` 和 `fetch_account_analytics` 同步修复。
- **测试账号**：已添加 @nba（NBA TikTok），使用占位凭据。真实同步需要有效的 TikTok Content Posting API OAuth 凭据。

### Douyin 适配器修复

- **请求节流**：添加 `min_request_interval`（默认 0.3 秒）和 `_throttle` 方法，防止短时间大量请求触发限流。
- **测试账号**：已添加咪咕体育抖音（sec_uid=MS4wLjABAAAA_migutiyu），使用占位凭据。真实同步需要有效的抖音开放平台 OAuth 凭据。

### YouTube 适配器

- 适配器已完全实现（channels + playlistItems + videos 批量查询），无需修复。
- **测试账号**：已添加 ESPN（channel_id=UCiio0ydw439X13KyZgMIcHw）。需要有效的 YouTube Data API v3 Key（通过 `SIO_YOUTUBE_API_KEY` 环境变量或账号级 `adapter_config.api_key`）。

### 已知限制

- Bilibili 首次同步大量视频（>60 条）时可能触发限流，导致运行标记为 "error"，但已获取的数据仍会持久化。后续增量同步仅处理新视频，通常可成功完成。
- TikTok、Douyin、YouTube 需要真实 API 凭据才能完成同步；占位凭据会返回 `authentication_error`。
- Bilibili WBI 密钥每 30 分钟自动刷新，Cookie 初始化仅在适配器首次请求时执行一次。

## 2026-07-28 新闻同步修复与前端功能增强

### 新闻源同步修复

- **SSRF 检查可配置化**：Docker 环境的 DNS 将外部主机名解析为 198.18.x.x（RFC 2544 基准测试地址段），导致 `ensure_public_endpoint` 的 `is_global` 检查拒绝所有外部 URL。新增 `SIO_NEWS_SSRF_CHECK_ENABLED` 配置项（默认 true），开发环境设为 false 跳过 DNS 解析检查，仅保留 URL 格式与私有 IP 字面量校验。
- **HTTP 重定向支持**：Feed 和 JSON Feed Provider 的 httpx 客户端添加 `follow_redirects=True`，修复 Deadspin 等使用 308 永久重定向的源。
- **验证结果**：CBS Sports Headlines 同步成功（36 篇文章），系统总计 170 篇文章。ESPN 因容器 OpenSSL 与 CDN TLS 指纹不兼容返回 SSL 握手失败，属外部兼容性问题。

### 新闻热点页增强

- **按源筛选**：新增来源下拉选择器，支持按 UUID 过滤文章。
- **扩展筛选条件**：新增联赛、国家（ISO）、起始/截止日期、最低热度筛选；可折叠的"更多筛选"面板，带活跃筛选计数和一键清除。
- **刷新/同步按钮**：页面顶部"刷新"按钮一键触发所有已启用源的异步同步任务。
- **管理源入口**："管理源"按钮链接到设置页新闻源 Tab（支持 `?tab=sources` URL 参数直达）。
- **分页信息**：显示"第 X 页 / 共 Y 页"。

### 缩略图与视觉增强

- **账号列表**：表格"账号"列新增圆形头像（avatar_url），无头像时显示名称首字。
- **账号详情页**：页头新增 64px 圆形头像；"作品"Tab 每条内容新增封面缩略图（cover_url）。
- **作品详情页**：有封面时在指标卡片上方显示全宽圆角封面图。

### 设置页「平台管理」Tab

- 新增"平台管理"标签页，集中展示所有已启用平台的适配器状态（已实现/骨架）、关联账号列表及凭证配置状态（已配置/未配置），点击可跳转到对应账号设置页。

### 账号监控详情页优化

- **同步记录增强**：显示中文状态标签（成功/失败/同步中/排队中）、耗时计算、适配器标识、新增/更新记录数高亮、错误码与错误信息。
- **自动刷新**：账号处于 queued/syncing 状态时，账号详情和同步记录每 5 秒自动轮询，实时展示同步进度。

## 2026-07-28 浏览器模拟爬取与设置页重构

### 历史实现：全平台默认浏览器模式（已被条件路由取代）

该阶段曾把 Playwright 设为四个平台默认方式；当前已改为 `api`、`public_page`、`authorized_login`、`authorized_session` 条件路由，官方 API 权限足够时必须优先。

架构设计：

- **`browser_base.py`**（BrowserPlatformAdapter 基类）：管理 Playwright 生命周期；反检测（webdriver 遮蔽、真实 UA/viewport）；礼貌延迟；可选登录钩子。
- **`bilibili_browser.py`**：拦截 WBI API 响应 + DOM 降级。
- **`youtube_browser.py`**：拦截 youtubei 内部 API + DOM 降级。
- **`tiktok_browser.py`**：解析嵌入 JSON + 拦截 user/detail API。
- **`douyin_browser.py`**：解析 RENDER_DATA + 拦截 aweme/post API。

数据库 platforms 表仅保留 4 条记录（youtube/tiktok/douyin/bilibili），adapter_key 指向对应的 browser 适配器。已删除所有 `*_browser` 独立平台记录。

### 设置页「平台管理」重构

- 删除原有的适配器状态、关联账号列表展示。
- 改为纯登录凭证配置面板：每个平台一张卡片，标题"XXX 登录凭证"（青色），说明文字，凭证输入字段（用户名/密码/Cookie），保存按钮。
- 该广播明文配置方式已废弃；当前使用工作区级加密平台凭证表，并迁移/删除历史 `metadata.adapter_config` 明文。

### LLM API 设置增强

- 新增"模型提供商"下拉框，预设 8 个主流 LLM Provider：OpenAI、Anthropic (Claude)、Google Gemini、DeepSeek、OpenRouter、Ollama（本地）、Moonshot (Kimi)、智谱 AI (GLM)。
- 选择提供商后自动填充 Base URL、默认模型和配置名称。
- 所有提供商均通过 OpenAI 兼容接口对接，共享同一套配置表单。

### 部署变更

- `deploy/api.Dockerfile`：pip install 与 playwright install 分离为独立层；playwright 安装添加 3 次重试。
- `apps/api/pyproject.toml`：新增 `playwright>=1.52,<2`。
- 环境变量 `PLAYWRIGHT_BROWSERS_PATH=/opt/browsers`。

### 已知限制

- Bilibili 视频列表在高频测试后触发 -799 限流，属临时外部限制。
- 浏览器适配器不支持私有分析数据，相关指标标记为 unavailable。

## 2026-07-29 登录模式选择、匿名优先爬取与趋势分析

### 历史实现：平台凭证双模式选择（现已扩展为四模式）

设置页平台管理每张凭证卡片新增登录模式选择器（API 密钥 / 账号登录）：

- **API 密钥模式**：显示平台官方 API 所需字段（YouTube: API Key；TikTok: Client Key/Secret/Access Token；抖音: Client Key/Secret/Access Token；Bilibili: SESSDATA Cookie）。
- **账号登录模式**：显示浏览器模拟所需的用户名/密码字段，可留空使用匿名访问。
- 当前模式和密文写入 `platform_credentials`；不再向账号元数据广播秘密。
- 后端同步服务 `SyncService.request_account_sync` 根据 mode 自动路由：API 模式使用基础适配器（youtube/tiktok/douyin/bilibili），浏览器模式使用 `*_browser` 适配器。
- `PlatformSyncExecutor._config_for` 更新为 mode 感知：API 模式下 YouTube 自动注入全局 `youtube_api_key`。

### 匿名优先爬取策略

浏览器适配器基类（`browser_base.py`）重构为匿名优先策略：

- 默认匿名访问，不主动尝试登录。
- 新增 `LoginRequiredError` 异常类（code="login_required"），当检测到平台登录墙时抛出。
- 新增 `_check_login_required` 方法：检查 URL 重定向（passport.bilibili.com、accounts.google.com 等）和 DOM 登录弹窗（.login-panel-popover、.bili-mini-mask 等）。
- `_login_if_configured` 仅在凭证存在且系统重试时调用，不主动触发。
- 同步服务捕获 `LoginRequiredError` 后将错误码和提示消息写入账号，前端可展示"请在设置中配置登录凭证"。

### 趋势分析系统（全新功能）

新增 `/trends` 趋势分析页面，支持跨平台视频宏观趋势发现：

**后端**（3 张新表 + 5 个 API 端点）：

- `trend_topics`：平台趋势话题（heat_score、growth_rate、rank、sample_size）
- `trend_videos`：爆款视频（view/like/comment/share 计数、breakout_score、author 信息）
- `trend_keyword_snapshots`：关键词趋势快照（video_count、total_views、avg_views、heat_index）
- `GET /trends/dashboard`：聚合热门话题、爆发视频和各平台概要统计
- `GET /trends/topics`：分页话题列表，支持平台筛选，按热度排序
- `GET /trends/videos`：分页视频列表，支持平台筛选和自定义排序（breakout_score、view_count 等）
- `GET /trends/keywords`：关键词快照，支持模糊搜索和平台筛选
- 旧 `POST /trends/seed` 演示入口已移除；当前由真实 Provider 与定时采集任务写入趋势观测。

**前端**（趋势分析仪表板）：

- 平台筛选标签（全部/YouTube/TikTok/抖音/Bilibili）
- 4 张平台概览卡片（话题数、视频数、平均热度），各平台主题色
- 热门话题排行榜（热度进度条、增速指标、平台标签）
- 爆款视频发现面板（封面图、作者、播放/点赞统计、breakout score 徽章）
- 赛道趋势图表（Recharts 分组柱状图，关键词热度跨平台对比）
- 关键词统计表（视频数、总播放、热度指数）
- 当前按钮为“采集真实数据”，不会生成示例趋势。

**导航**：侧边栏新增"趋势分析"入口（TrendingUp 图标），位于"新闻热点"之后。

### 数据真实性声明

- 旧演示趋势已停止使用；历史未验证记录标记为 `imported/legacy_unverified` 并排除在实时看板之外。
- 匿名优先爬取策略下，所有公开数据采集不依赖用户凭证；需要登录的场景通过 `LoginRequiredError` 显式告知用户。

### 已知限制

- 趋势采集 Celery 任务已实现；当前真实覆盖取决于各平台有效授权和网络可用性。
- 趋势分析前端使用 Recharts 静态图表，尚未实现实时更新（WebSocket/SSE）。
- API 模式与浏览器模式的切换仅影响同步时的适配器选择，不影响已保存的同步历史记录。

## 2026-08-02 账号监控增强：抓取量级、资料扩展、可配置抓取参数

围绕账号监控的 7 项产品反馈完成端到端改造（需求来源：超长任务清单 #1–#7）。

### 1. 作品获取不全（仅 ~20–50 条）→ 真实翻页 + 单次量级上限

根因：yt-dlp 适配器此前固定 `playlist_end=max(page_size,50)` 并在单页内截断，且始终返回 `next_cursor=None`，导致每次同步只抓第一窗口（≤50 条）。

修复：
- `app/adapters/platforms/yt_dlp.py` 的 `list_contents` 改为**基于游标的窗口翻页**：按 `playlist_start/playlist_end` 递增窗口，返回 `next_cursor` 直到窗口未被填满为止；首个空页（翻页中途）不再误触发浏览器兜底，避免重复从头抓取。
- 新增 `accounts.max_contents_per_sync`（每账号单次同步最多抓取作品数，NULL=全局默认）。
- `_sync_contents` 以 `max_contents_per_sync` 为硬上限收敛总抓取量；窗口随剩余预算收缩。
- 离线单测覆盖：120 条 3 页无重复、max_items 截断、`published_after→dateafter`、`extra_args` 透传、空尾页不兜底。

### 2. 账号详情页新增 Bio / 认证 / 地区 / 粉丝信息

- `account-detail-client.tsx` 头部下方新增独立「资料卡」：展示简介（Bio）、官方认证徽章（`is_verified`）、国家/地区、外部 ID、粉丝数（`formatNumber`）。标题行在已认证时追加 `✓`。

### 3. 每次同步判断头像/签名等是否需要更新

- 既有 `_sync_account`（sync.py ~646–651）已在每次同步对账 `avatar_url / description / country / is_verified / language`，覆盖该需求，无需额外改动。

### 4. 添加账号简化：首次只需账号网址

- `AccountCreate.display_name` 改为**可选**；后端 `create_account` 在缺省时回退为 `external_id`，同步后由真实资料覆盖。
- 添加账号表单精简为「平台 + 账号主页网址/频道 ID + 可选显示名称」，用户名/主页/同步周期等移至详情页「设置」中编辑。

### 5. 所有平台作品列表显示封面

- 各适配器已填充 `cover_url`，前端作品列表与账号详情作品表均通过 `ExternalImage` 渲染封面（缺失时 `<Film>` 占位）。本项已满足，仅统一占位样式。

### 6. 数据最少精确到小数点后 1 位

- `formatPercent` 统一 `(v*100).toFixed(2)`（≥2 位小数）。
- 将两处 `toFixed(0)` 计分展示改为 `toFixed(1)`（`score-explanation.tsx` 权重百分比、`trends-client.tsx` 爆发分），保证所有展示数据 ≥1 位小数。

### 7. 抓取去重 + 可配置 yt-dlp 参数（页面设置）

- **去重**：`_upsert_content` 新增 `skip_existing`；开启后已存在作品保留运营可编辑字段（标题/封面/网址），仅刷新 `last_seen_at` 与指标快照，不覆盖手工数据。`account.adapter_config.yt_dlp.skip_existing` 控制。
- **可配置参数**：新增 `accounts.adapter_config`（JSON），在 `_config_for` 中合并进 `AdapterCallContext.config` 并嵌套到 `yt_dlp` 下；适配器支持 `dateafter` / `datebefore`（日期区间）、`max_items`（总量上限）、`extra_args`（yt-dlp 透传参数）。
- **前端「设置 → 抓取设置」卡片**：单次最多抓取数、dateafter/datebefore 日期选择器、跳过已存在开关，附行业最佳实践提示文案；同步周期仍在上方的「同步周期」字段设置。

### 数据模型与迁移

- `Account` 新增 `max_contents_per_sync: BigInteger NULL` 与 `adapter_config: JSON NOT NULL DEFAULT '{}'`，并加 `max_contents_per_sync >= 1` 检查约束。
- 迁移 `20260802_0025_account_scrape_config.py`：按既有风格 `add_column` + `create_check_constraint`；对存量行回填 `'{}'::json` 满足 NOT NULL。
- `AccountCreate / AccountUpdate / AccountRead` 与前端 `AccountRecord` 同步新增 `max_contents_per_sync`、`adapter_config`。

### 验收命令（需 Docker PG 测试栈）

- `docker compose run --rm api sh -lc "cd apps/api && pytest tests/test_yt_dlp_adapter.py"`
- `docker compose run --rm web pnpm --filter @sio/web typecheck`
- `docker compose run --rm api sh -lc "cd apps/api && ruff check app tests"`
- `docker compose run --rm api sh -lc "cd apps/api && alembic upgrade head"`

### 已知限制

- 真实 YouTube/TikTok/抖音 抓取仍需本机可用 `yt-dlp` 与出网环境；离线单测已覆盖适配器分页/配置逻辑，但端到端量级需在可出网容器中验证。
- `max_contents_per_sync` 仅约束单次同步抓取量，不删除历史已抓取作品；如需清理存量需在业务层另行处理。
- 浏览器兜底适配器不受 `playlist_start/end` 翻页控制，仅 yt-dlp 主路径支持窗口翻页。

### 2026-08-02（续续续）：补齐用户反馈中"仍没解决"的三项 — 强制全量回填 / 平台自动识别 / 报错双详情

本轮直接回应用户「以下问题依然没解决」清单中的 #1、#4，以及新增的「对所有报错给出代码级 + 业务层错误详情」要求。代码已落地并通过 ruff / mypy / tsc / 单测，镜像已重建部署（api / worker / beat / web）。

#### #1 作品获取不全（仍 ~20 条）— 根因是增量窗口永不回填，新增「全量重新同步」

- **根因（关键）**：上一轮虽然把 yt-dlp 改成了游标窗口翻页，但 `_sync_contents` 在**每次同步都传入 `published_after=newest_seen`**（纯增量模式）。早期由旧单窗口代码播种的账号 `newest_seen` 被永久定格在首屏 ~20 条，之后每次增量都只抓比这 20 条更新的作品，旧历史永远无法补回 → 账号始终只有 ~20 条。
- **修复**：`SyncService.request_account_sync` 新增 `force_full: bool`；`POST /accounts/{id}/sync` 接受可选请求体 `{"force_full": true}`。当 `force_full=True` 时 `_sync_contents` 把 `published_after` 置为 `None`，走「全量回填」路径，把账号历史作品一次性补齐（仍受 `max_contents_per_sync` 与 yt-dlp 窗口翻页约束，最多 1000 条）。
- **前端**：账号详情页「立即同步」旁新增「全量重新同步」按钮，调用 `POST /accounts/{id}/sync` 带 `force_full: true`。被旧代码卡住、长期只有 20 条的账号，点一次「全量重新同步」即可补齐历史。

#### #4 添加账号简化 — 首次只需网址，去掉平台下拉，新增自动识别

- **纠正上一轮偏差**：上一轮「账号监控增强」小节仍保留了「平台 + 网址」的表单（平台 `<select required>`）。用户明确要求**不需要选择平台、由系统自动判断**。本轮已删除平台下拉框。
- **实现**：新增 `app/services/platform_detect.py` 的 `detect_platform_key_from_url(raw_url)`，依据 URL 主机名（含 `youtube.com`/`youtu.be`/`tiktok.com`/`douyin.com`/`v.douyin.com`/`bilibili.com`/`b23.tv` 及 `@platform/...` 句柄、短链）自动映射平台 key；无法识别时返回 `None`，`create_account` 抛出中文校验错误「无法从网址识别平台…」。
- **后端**：`AccountCreate.platform_id` 改为 `UUID | None = None`；`create_account` 在 `platform_id is None` 时自动探测，找不到平台或平台未启用则给出清晰中文报错。`repositories/monitoring.py` 新增 `get_platform_by_key`。
- **前端**：`accounts-client.tsx` 添加账号表单移除平台下拉，仅保留「账号主页网址（全宽，placeholder 提示 YouTube / TikTok / 抖音 / Bilibili）」+ 可选显示名称；`createAccount` 不再发送 `platform_id`。名称、同步周期等可在同步后于详情页编辑。离线单测 `test_platform_detect.py` 6 passed。

#### 全量报错双详情 — 代码级 + 业务层（新增要求）

- **数据层**：`sync_runs` 新增两列 `error_detail`（代码级：`ExceptionType: msg | adapter=X | run=Y | request_id=Z`）与 `error_hint`（业务层：按 `error_code` 映射的中文说明 + 处置建议）。新增迁移 `20260802_0030_sync_run_error_detail.py`（`down_revision=20260802_0025`）。
- **填充点（覆盖所有报错路径）**：`services/sync.py` 新增 `code_level_detail(exc, *, run, adapter_key)` 与 `business_hint_for(code, adapter_key)`（15 个语义错误码 → 中文业务解释与修复动作），并在 `_terminal_error`、重试分支 `except PlatformAdapterError`、兜底 `except Exception`、以及 `mark_dispatch_failure` / `_release_stuck_run` 全部写入 `error_detail` + `error_hint`。
- **Schema / 前端**：`SyncRunRead` 增加 `error_detail` / `error_hint`；`shared-types` 的 `SyncRunRecord` 同步增加；账号详情页主错误面板与同步记录列表错误项均渲染「业务层说明与处置建议」+「代码级错误详情」`<pre>` + 错误码 Badge。
- 质量门禁：ruff / mypy（7 文件）/ `pytest tests/test_platform_detect.py`（6 passed）/ `tsc -p apps/web --noEmit`（exit 0）全绿；修复了 `account-detail-client.tsx` 因两个同步按钮缺少单一父元素导致的 `TS2657`（已用 `<>...</>` 包裹）。

#### 本轮状态小结

| 用户反馈项 | 本轮处理 |
| --- | --- |
| #1 作品获取不全 | 新增「全量重新同步」`force_full` 路径，回填被增量窗口锁死的历史作品 |
| #2 账号级 Bio 等扩展 | 上一轮「资料卡」已实现（Bio / 认证 / 地区 / 粉丝），本轮核对保留 |
| #3 同步时判断头像/签名是否更新 | `sync.py` `_sync_account` 每次对账 `avatar_url/description/country/is_verified/language`，已实现 |
| #4 添加账号简化、自动识别平台 | 删除平台下拉，新增 `platform_detect` 自动识别，添加只需网址 |
| #5 作品列表封面 | 各适配器填 `cover_url` + 前端 `ExternalImage`，已实现 |
| #6 数据≥1 位小数 | `formatPercent` ≥2 位；两处展示改 `toFixed(1)`，已实现 |
| #7 去重 + 可配置抓取参数 | `skip_existing` + `adapter_config.yt_dlp`（dateafter/datebefore/max_items/extra_args）+ 设置页抓取卡片，已实现 |
| #9 报错双详情 | `sync_runs.error_detail`/`error_hint` + 全路径填充 + 前端渲染，本轮新增 |

## 系统操作留痕「报错双详情」全链路（2026-08-02 续）

用户需求：**系统操作留痕（日志/审计/外部调用/死信/后台任务等）中所有报错，都要同时给出代码级错误详情与业务层错误详情**。

- 数据层：`app/services/error_detail.py` 单一真相源（`code_level_detail` + `business_hint_for`，含 13 个 operation 错误码，未知码走通用兜底）；`system_events`/`audit_entries`/`external_call_attempts`/`task_runs`/`outbox_event_attempts`/`dead_letter_events`/`news_sync_runs`/`generation_runs` 加 `error_detail`/`error_hint`/`error_code`/`status` 列；迁移 `20260803_0001`。
- 写入点：新增 `app/services/audit.py`（`build_audit_entry`/`build_external_call_attempt`，失败自动派生业务 hint）；`operations.py` 聚合器 + `news/generation/sync/automation` 的 SystemEvent/ExternalCallAttempt/NewsSyncRun/GenerationRun 错误路径、outbox 死信路径全部补齐双详情；`operations` 路由的 events/audits/tasks 接口返回新字段。
- 前端：`logs-client.tsx`（系统事件 + 审计日志双表「错误详情」列：错误码 Badge + 代码级 `<pre>` + 业务层「处置建议」）、`external-calls`（详情面板业务层说明）、`dead-letters`（修正历史 `last_error`→`last_error_*` 字段错位并渲染双详情）、`tasks`（任务列表「错误详情」列）。
- 验证：`docker compose build api worker beat web` 成功；`up -d` 后迁移 `20260802_0030 -> 20260803_0001` 已应用；8 表共 24 个新列入 DB；OpenAPI 暴露全部新字段；ruff 0 错、前端 tsc 0 错。

## 同步「媒体下载」选择 + 作品详情「媒体资源」面板（2026-08-03）

用户需求：在「同步设置」中开放 yt-dlp 的**下载参数**（封面缩略图 / 字幕 / 视频 / info.json 等），让操作员选择同步时归档哪些本地媒体；作品详情页新增「媒体资源」面板，已下载则渲染（img / video / 字幕列表 / JSON 链接），未下载则最小化显示「X 未下载」（布局参考行业优秀案例）；列表页已展示封面，本任务不改列表。

- **默认下载项（用户确认）**：封面 + 字幕默认开（`write_thumbnail` / `write_subtitles` → `True`，`subtitle_langs="zh.*,en.*"`）；自动字幕 / 视频 / info.json 默认关（避免占盘）。
- **存储方式（用户确认）**：本地卷 + API 路由。媒体写入 api 容器挂载卷 `./media`（= `SIO_MEDIA_ROOT`），按 `MEDIA_ROOT/<workspace_id>/<handle>/<video_id>/` 分层；详情页 `<img>/<video>` 与字幕链接经新增 `GET /api/v1/media/{content_id}/{file}` 鉴权后流式访问。
- **后端 Schema**：`schemas/settings.py` 新增 `YtDlpDownloadSettings`（7 字段：write_thumbnail/write_subtitles/write_auto_subtitles/subtitle_langs/download_video/video_format/write_info_json，含 `_validate_video_prereq` 校验下载视频时 video_format 必填）+ `DEFAULT_SYNC_SETTINGS_CONFIG["download"]`；`SyncSettingsConfig` 增加 `download`；`SyncSettingsUpdate` 同步。
- **适配器落盘**：`adapters/platforms/yt_dlp.py` 新增 `_safe_dir`/`_any_download_enabled`/`_collect_media`（扫描每视频目录、分类缩略图/视频/字幕/info_json，返回相对**全局** `MEDIA_ROOT` 的 `base`）；`_run_yt_dlp` 新增 `download`/`media_dir` 形参，条件追加 `--write-thumbnail`/`--write-sub`/`--write-auto-sub`/`--sub-langs`/`--write-info-json`/`-f <video_format>` 与 `-o <media_dir>/%(id)s/%(id)s.%(ext)s`，仅当开启 `download_video` 才移除默认 `--skip-download`；`list_contents` 从 `ctx.config` 取 `download`/`media_root`，构 `media_dir` 并 `os.makedirs`，循环 `_collect_media` 注入 `media`。
- **同步注入 + 落库**：`services/sync.py` 的 `_config_for` 注入 `merged["download"]` 与 `merged["media_root"]=os.path.join(SIO_MEDIA_ROOT, workspace_id)`；`_upsert_content` 在新建与更新分支均落 `content.media = dict(data.media) if data.media else None`。`repositories/sync.py` 的 `get_sync_settings_config` 合并 `download` 默认值。
- **模型/迁移**：`models/monitoring.py` 的 `ContentItem` 新增 `media JSON` 列；迁移 `20260803_0004_add_content_media.py`（down_revision=0003）。
- **媒体鉴权路由**：`app/api/routes/media.py` 新增 `GET /api/v1/media/{content_id}/{file}`：以登录会话（`CurrentAuth`）+ 校验内容归属用户任一 active workspace 鉴权（因 `<img>/<video>` 无法带 `X-Workspace-Id` 头，故不依赖该头，以不可猜测的 content UUID 作能力凭证）；`_allowed_files` 限定文件名必须等于已记录的 thumbnail/video/info_json/subtitles file；`_safe_media_path` 用 `os.path.normpath` + `startswith(root+os.sep)` 防路径穿越；`os.path.isfile` 经 `anyio.to_thread.run_sync` 规避 ruff ASYNC240。`router.py` 已 include。
- **前端详情页**：`content-detail-client.tsx` 新增可复用 `MediaCard`（未下载时虚线边框 + 「未下载」+ 提示；已下载渲染子内容），在 Hero 封面与指标网格之间插入「媒体资源」Panel（封面/视频/字幕/原始信息四卡片），`mediaUrl=(file)=>/api/v1/media/${id}/${encodeURIComponent(file)}`。
- **前端设置页**：`sync-settings-panel.tsx` 新增 `DOWNLOAD_FIELDS`（7 字段）+ `DEFAULT_DOWNLOAD`，hydrate 填充 `download`、保存构造 `downloadBody` 并入 `config.download`；在 extra_args 前新增「媒体下载」fieldset（琥珀色边框 + 视频体积警告）。`shared-types` 新增 `YtDlpDownloadSettings` 接口、`SyncSettingsConfig.download`、`ContentMedia` 接口（`base/thumbnail/video/info_json/subtitles`）。
- **测试库 schema 漂移永久修复**：持久化测试库 `sports_intelligence_test` 因 `Base.metadata.create_all` 不 alter 既有表，新增 `content_items.media` 列导致 14 项非相关测试误报 `UndefinedColumnError`。将 `conftest.py` 的 `setup_test_db` 会话级 fixture 改为**每次会话 DROP + 重建**测试库（`pg_terminate_backend` + `DROP DATABASE` + `CREATE DATABASE` 后 `create_all`），彻底消除该类漂移（测试以 `isolate_db` 逐测试 TRUNCATE，重建无副作用）。
- **验证**：后端 ruff 全绿；全量 `pytest` **126 passed**（recreate 修复后）；前端 `tsc --noEmit` 0 错误；`docker compose build api worker beat web` + `up -d` 应用迁移 `0004` 待实机验收。`docs/STATUS.md` 与 `.workbuddy/memory/2026-08-03.md` 更新。改动本地、待提交（不推送）。

## 账号监控：下载默认/同步弹窗/签名/缩略图/比对修复/全量测试（2026-08-03 续）

用户 7 项需求：①新增账号默认下载设置并持久化 ②每次同步弹窗选下载内容并记独立设置 ③详情页账号名下方显示签名 ④作品清单标题前显缩略图 ⑤彻查同步仍只 20 条+无头像/签名/缩略图 ⑥比对报错 ⑦全量测试（含自动化链路）。

- **后端（子 agent 完成）**：`models/monitoring.py` 的 `Account` 新增 `sync_settings_override JSON` 列 + 迁移 `20260803_0005`；`schemas/monitoring.py` 新增 `AccountSyncSettingsOverride`（`download: YtDlpDownloadSettings`，`extra="forbid"`）；`services/monitoring.py` 新增 `get/update_account_sync_settings`（含审计）；`routes/monitoring.py` 新增 `GET|PATCH /accounts/{id}/sync-settings`（CsrfProtectedAuth + 角色校验）；`shared-types` 补 `AccountSyncSettingsOverride` 与 `AccountRecord.sync_settings_override`；`services/sync.py` 的 `_config_for` 深合并账号 `download` 覆盖到工作区策略（`_deep_merge_download`）；`yt_dlp.py` 的 `resolve_account` 在 avatar/description 缺失时 best-effort 浏览器回退补头像签名、`fetch_account_analytics` 在 follower 缺失时回退合并、`list_contents` 对 TikTok/Douyin 窗口未满即回退浏览器适配器；`tiktok_browser.py` 滚动 10 次。回归：ruff 绿、定向 25 passed、全量 132 passed。
- **前端（本轮落地）**：新增 `components/download-settings-fields.tsx`（复用 `YtDlpDownloadSettings` 7 字段，`DEFAULT_DOWNLOAD_SETTINGS`）；新增 `components/sync-settings-modal.tsx`（拉账号 override + 工作区默认 → `PATCH` 保存独立设置 → `POST` 同步）；`accounts-client.tsx` 添加账号表单接入下载默认 UI 并 localStorage 记忆（`sio-account-download-defaults`，满足"记录设置值以供下次使用"），同步按钮改开弹窗；`account-detail-client.tsx`「立即同步」改开弹窗；签名（description 区块）与作品清单封面列此前已在 UI，靠后端补数据生效；`account-compare-client.tsx` 改 `page_size=200`→`100`（修复 422→比对按钮 disabled）。
- **验证（浏览器自查 + 接口）**：`tsc` 0 错、`next build`（docker）成功、ruff 绿、全量 `pytest 132 passed`；Playwright 经 `localhost:8080` 自查：比对页复选框 **22 个**（修复前 0）、添加账号表单显「下载内容默认设置」、同步按钮弹窗显下载字段；API `GET|PATCH /accounts/{id}/sync-settings` 往返持久化成功。真实同步抽样：**YouTube 账号同步返回 850 条作品**（非 20）、`description=True`(签名)、`avatar=True`、`cover_url=True`(缩略图)——证明头像/签名/缩略图补全与分页修复生效。
- **已知限制（TikTok/Douyin）**：yt-dlp 对 TikTok/Douyin 首页仅返回 ~20–23 条即标记结束，浏览器回退逻辑已加入但被平台反爬拦截（返回 0），故这两平台仍可能只抓到 ~20 条；属平台反爬限制，非代码缺陷。YouTube 走 yt-dlp 分页窗口化，可抓全量。
- **部署**：`docker compose build api worker beat web` + `up -d` 已应用迁移 `0004→0005`（`sync_settings_override` 列已落库）；迁移 0005 经 api 启动 `alembic upgrade head` 自动应用。本地调试库 admin 密码曾临时改为 `Admin123!`。改动本地、待提交（不推送，排除 `.workbuddy/`）。

## 同步策略重构：yt-dlp 优先 + 抓取数据设置 + 现有账号同步修复（2026-08-03）

用户 4 项需求：①执行 git push ②优先独立用 yt-dlp 抓全量视频，仅在 yt-dlp 出问题/不可用时才启动浏览器兜底 ③同步弹窗新增「抓取数据设置」（单次抓取数量/抓取范围等）④现有账号前端同步仍不成功，定位并解决。

### ① git push
- 分支 `codex/full-repair-real-data` 已 `git push -u origin` 上 GitHub（PR 已生成）。本轮新增提交亦已推送。

### ② yt-dlp 优先、浏览器仅作兜底（核心重构）
- **删除 3 处"软缺口回退"**（上一轮"头像/签名缺失→浏览器补""follower 缺失→回退合并""TikTok/Douyin 窗口未满→回退浏览器"）：这些逻辑会让 yt-dlp 一旦缺字段就切浏览器，违背"优先独立用 yt-dlp"的意图。`adapters/platforms/yt_dlp.py` 的 `resolve_account`/`fetch_account_analytics`/`list_contents` 现仅在**硬失败（yt-dlp 抛 `TransientAdapterError` 或首页为空）**时回退浏览器；部分窗口（返回数 < 请求数但非空）视为目录正常结束、`next_cursor=None`，不触发切换。
- **修复 Douyin 崩溃根因**：yt-dlp 对不支持的账号（如 Douyin）输出字面量 `null` → `json.loads("null")` 得 `None`，下游 `data.get(...)` 抛 `AttributeError: 'NoneType' object has no attribute 'get'`，整轮同步落入兜底 `except Exception` → `unexpected_sync_error`。`_run_yt_dlp_single` 现对非 dict（null/列表/标量）统一返回 `({}, err_text)`，交由调用方决定回退，不再崩溃。
- **`list_contents` 支持账号级 `playlist_start`**：首页（offset==0）时若 `yt_cfg["playlist_start"]` 存在则跳过目录前 N 条，满足"起始位置"抓取需求。
- **回归测试**：`test_yt_dlp_adapter.py` 改写 `test_tiktok_partial_window_falls_back_to_browser` → `test_tiktok_partial_window_does_not_fallback`（断言不回退、返回 yt-dlp 条目、`next_cursor=None`）；新增 `test_run_yt_dlp_single_null_payload_is_safe`（null 输出返回 `{}`）+ `test_resolve_account_null_profile_falls_back_gracefully`（null 档案优雅回退浏览器）。

### ③ 同步弹窗新增「抓取数据设置」
- **后端 Schema**：`schemas/monitoring.py` 新增 `AccountSyncFetchSettings`（`max_contents` 1–5000、`dateafter`、`datebefore`、`playlist_start` 1–100000，均 `Optional`）。`AccountSyncSettingsOverride` 增加 `fetch: AccountSyncFetchSettings | None`。
- **合并到执行器**：`services/sync.py` 的 `_config_for` 在合并 `download` 后，将账号 `fetch` 覆盖深合并进 `yt_cfg`（`max_contents→max_items`、`dateafter`/`datebefore`/`playlist_start` 直接透传）。`fetch` 复用既有 `sync_settings_override` JSON 列，无需新迁移。
- **前端**：新增 `components/fetch-settings-fields.tsx`（导出 `DEFAULT_FETCH_SETTINGS` + `FetchSettingsFields`：单次抓取数量 / 起始位置 / 抓取范围起止日期，YYYYMMDD↔YYYY-MM-DD 互转）；`shared-types` 补 `AccountSyncFetchSettings` 接口与 `AccountSyncSettingsOverride.fetch`；`sync-settings-modal.tsx` 在「下载内容选择」上方新增「抓取数据设置」分组，加载时 override→工作区默认 兜底，`PATCH` body 改为 `{ download, fetch }`。

### ④ 现有账号前端同步失败：定位与修复（实证排查）
- **根因 A（Douyin `theolympics`）**：如上 ②，`unexpected_sync_error`（`NoneType.get` 崩溃）。部署后该账号 08:14 的同步已从 `error/unexpected_sync_error` 变为 **`degraded`「指标提取失败，仅更新了账号资料」**——不再崩溃，yt-dlp 优先、缺失指标经 `unavailable_metrics` 上报，整轮正常结束。
- **根因 B（孤儿 run 卡死）**：旧 `recover_stale_runs` 仅回收 `lock_key IS NOT NULL` 的卡死 run；部分 run 在其 worker 死前未写入 `lock_key`（空），永久停留在 `running`，UI 显示"同步中"但**按 `lock_key=account:{id}` 去重并不阻塞再同步**——属误导性卡死状态。实测发现 3 条孤儿 run（15 小时~1 天前，含 `youtube_browser`×2 与 `youtube_ytdlp`×1），已手动置为 `error`（保留账号状态，因各账号均有更新的已完成 run）。
- **加固 reaper**：放宽 `recover_stale_runs` 为"按失活（无近期心跳）回收，不再限定 `lock_key` 非空"，使空锁孤儿也能被 beat 周期清理；`_release_stuck_run` 增加守护——仅当该孤儿是账号**最新** run 时才重置 `account.sync_status`，避免覆盖已成功的 newer run。新增 2 个回归测试（`test_recover_stale_orphan_without_lock_key` / `test_recover_stale_orphan_keeps_newer_completed_status`）。
- **根因 C（Bilibili）**：`retry_exhausted / LoginRequiredError`，平台要求登录，属平台限制非代码缺陷，未改。

### 验证
- 后端：ruff 全绿；全量 `pytest`（Docker PG）**134 passed**；新增/改写测试均通过。
- 前端：`tsc --noEmit` 0 错；`eslint` 0 错；`next build`（docker）成功并 `up -d`，web 容器 `Healthy`、API `/health/ready` 与 proxy `/login` 均 200。
- 实机：Douyin `theolympics` 同步由崩溃转为 `degraded`（修复确认）；3 条孤儿 run 已清理；beat reaper 加固后可持续自愈。
- 部署：`docker compose build api worker beat web` + `up -d` 重建 4 个服务并应用；提交 `0d6cdfe` 已推送 origin。
- 注：本地 `next build` 因沙箱 safe-delete 对 `.next` 清理触发 50 文件批量删除确认而中断（非代码错误）；以 docker 内 `next build` 为准。
