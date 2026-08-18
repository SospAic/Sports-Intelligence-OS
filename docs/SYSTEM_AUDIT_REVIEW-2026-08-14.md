# Sports Intelligence OS 当前系统全面审计复审

日期：2026-08-14
审计对象：当前工作树、Docker Compose 运行环境、API/Web 测试与既有前端验收记录
审计性质：基于现有实现的可运行性、正确性、可靠性、安全性、性能和扩展性复审；不把规划项或 Mock 能力计入真实完成度。

## 一、结论摘要

当前系统已经从静态原型进入“可登录、可操作、可持久化、可追踪的内测版”。账号监控是当前实现最成熟的核心链路：已经具备 yt-dlp 快速枚举、按平台限制并发、增量跳过、分页游标、心跳、超时预算、停滞回收、取消、降级状态、脏数据保留、媒体清单合并和详细进度日志。

但系统目前还不能被定义为生产级高可用系统，主要原因不是缺少页面，而是以下四类基础能力还没有形成生产闭环：

1. “已下载”主要依据数据库媒体清单，尚未统一做文件存在性、大小、MIME、可读性和 checksum 校验；历史坏文件可能继续显示为已完成。
2. 多账号、多平台并发仍以单次同步和适配器内部限速为主，没有统一的全局平台配额、租约、队列优先级和可观测 SLO。
3. 热点情报当前仍以已监控作品和 YouTube API 趋势为主，新闻需要配置来源；距离“全网 24–72 小时最新热点”还差独立的跨平台/跨来源采集层。
4. 关键静态质量门禁尚未清零：Ruff 当前有 2 个错误，按 API 项目目录正确运行的 mypy 有 67 个错误；API 全量测试当前收集到 617 个用例，但本轮只执行了关键分组，不能宣称全量通过。

因此建议把当前版本定位为：**功能可用的内测/运营试用版，生产发布前必须完成 P0 可靠性和验证门禁**。

## 二、审计证据

| 项目 | 当前证据 | 判断 |
| --- | --- | --- |
| API | 19 个路由文件、209 个路由声明 | 业务面覆盖较完整，但缺少统一领域契约和类型门禁 |
| Web | 40 个页面入口、21 个 Vitest 文件、75 个前端测试 | 交互覆盖广；自动化功能 E2E 仍偏少 |
| API 测试 | 70 个测试文件；`pytest --collect-only` 收集 617 个用例 | 覆盖面广，但全量执行稳定性和耗时仍未达门禁 |
| 关键 API 回归 | 同步并发/停滞、数据保留、下载进度、评论、热点、自动化、权限共 53 passed | 核心风险链路当前回归通过 |
| Web 回归 | 21 个文件、75 个测试全部通过 | 前端组件/契约层通过 |
| 运行态 | API live/ready 与 Web `/login` 均返回 200；Compose 核心容器 healthy | 当前单机运行正常 |
| 数据库 | Alembic `20260813_0003 (head)` | 迁移链与当前代码一致 |
| Ruff | 2 个错误：模型导入顺序、测试文件超长行 | 未达到严格静态门禁 |
| mypy | 正确工作目录下 18 个文件共 67 个错误，另有 `faster_whisper` 缺少类型声明 | 未达到严格类型门禁 |
| 真实平台 | 代码和契约测试覆盖 YouTube/TikTok/抖音/Bilibili；本轮未对所有平台做同一批次的真实生产采集 | 真实可用性仍需持续 canary |

既有的浏览器全量验收记录在 [FULL_SYSTEM_TEST_REPORT-2026-08-14.md](FULL_SYSTEM_TEST_REPORT-2026-08-14.md)，行业能力对照与此前的详细可行性分析在 [SYSTEM_AUDIT_FEASIBILITY_2026-08-14.md](SYSTEM_AUDIT_FEASIBILITY_2026-08-14.md)。本报告补充当前工作树的静态质量和关键回归复核结果。

## 三、分模块审计

### 3.1 账号监控与同步：最成熟，但仍是生产风险最高的链路

已具备：

- YouTube、TikTok、抖音、Bilibili 的适配器注册；YouTube/TikTok/抖音默认使用 yt-dlp 适配器，并保留浏览器回退路径。
- 快速目录枚举与按需完整解析；已存在作品可跳过，部分作品可补全。
- 默认单账号详情并发 4；适配器会按平台进一步限制，文档基线为 YouTube 8、Bilibili 4、TikTok/抖音 2。
- 每次运行默认 40 页、单页抓取 60 秒、单次运行 300 秒预算；运行队列 180 秒未接管或超过租约会回收。
- 账号锁、心跳、分页 cursor、取消、降级状态、单条失败继续、同步轨迹日志和 retryable/non-retryable 错误分类。
- 对已有作品采用媒体清单合并、非空字段更新、历史快照追加，已修复重复同步擦除字幕/评论/封面的问题。

需要完善：

- 没有统一的“平台级全局配额”：多个账号同时同步时，worker 默认并发、平台请求间隔、代理/IP、Cookie 会话和 yt-dlp 子进程预算没有集中调度。
- 游标目前主要以页级 checkpoint 持久化；页内大量作品在 worker 中断时，重试仍可能重复解析，缺少 item-level lease/idempotency 和可恢复批次。
- 账号详情的成功状态仍需要和字段级覆盖率、最后成功时间、数据新鲜度、被跳过数量、降级原因统一展示。
- 真实平台 canary 尚未形成每日固定样本、失败分类、版本回归和告警闭环。
- 仅有单机 Celery worker/beat，没有 worker 失联、Redis 重启、数据库连接池耗尽和平台长时间限流的混沌验证。

结论：**功能可用，P0 级可靠性待补齐**。账号同步应继续作为所有性能和可靠性工作的第一优先级。

### 3.2 作品、媒体和自定义播放器

已具备：作品列表/分页/筛选/排序/日历、作品详情、视频下载、原始 info.json、封面、媒体播放、自定义 YouTube 风格播放器、导出和任务日志。

主要缺口：

- `ContentItem.media` 仍是 JSON 媒体清单，不是独立 Artifact Registry；下载完成状态没有统一验证物理文件。
- `_media_file_ready` 当前主要根据清单值是否存在判断 ready，不能确认文件是否被手动删除、零字节、内容类型错误、路径失效或文件损坏。
- 本地 `media` 目录缺少清晰的容量上限、清理策略、保留策略、重复文件去重和对象存储迁移边界。
- 下载任务有 stale recovery 和滚动日志，但没有可靠的断点续传、单文件级重试、部分成功重试和任务级取消/恢复模型。
- 自定义播放器的时间显示已做有限数值裁剪，但媒体文件与元数据的时长、码率、分辨率仍应以实际媒体探测结果复核，不能只信平台返回值。

结论：**界面体验已具备，文件一致性和存储生命周期是 P0**。

### 3.3 字幕、ASR 与本地翻译

已具备：

- 平台原字幕与本地 ASR/翻译分离；faster-whisper 由独立 subtitle worker 执行。
- LibreTranslate 容器和语言代码归一化已修复，生成任务支持日志、目标语言选择和任务状态。
- 字幕时间轴复用、纯文本单行语义、双语展示、语言选择、时间戳开关、字幕导出和播放器联动已经有较完整的产品闭环。
- 没有真实轨道时不会伪造字幕；没有逐词边界时只做句级高亮。

需要完善：

- faster-whisper 和 LibreTranslate 目前没有模型版本、质量基准集、语言覆盖率、BLEU/COMET/人工抽检和失败重试指标。
- subtitle worker 固定 `concurrency=1`，适合保护资源但吞吐有限；没有按 CPU/GPU、视频时长、语言数和队列长度动态调度。
- 本地模型缓存没有清理/容量告警；翻译镜像使用 `latest`，可复现性和供应链稳定性不足。
- 逐词高亮依赖源轨道或 ASR 的真实 word timing；翻译后的逐词时间对齐尚未作为独立质量能力实现。
- 字幕文件同样需要纳入 Artifact Registry，不能只依据 `media.subtitle_artifacts` 条目判断生成完成。

结论：**产品闭环已可用，质量评估、资源调度和文件状态仍需 P1/P0 化处理**。

### 3.4 评论 Top 20

已具备：YouTube/部分 TikTok 等路径的评论归一化、Top 20 截断、作者/文本/时间/点赞/回复字段、来源标记和空结果保护；同步不会用空结果删除历史评论。

需要完善：

- 平台能力差异仍较大，评论采集可能受登录、地区、接口变化和权限影响；页面需要按 `observed / unavailable / login_required / stale` 明确展示。
- 当前 Comment 主要是当前状态行，没有独立的评论快照表，无法计算单条评论点赞/回复增长、排名变化和趋势告警。
- 缺少平台游标、分页水位、评论采集批次和“仅更新前 20 / 全量分页”的策略配置。

结论：**基础能力可用，评论趋势和高可靠增量采集是 P1**。

### 3.5 热点情报中心与新闻聚合

已具备：新闻源 CRUD、RSS/Atom/JSON/浏览器公开页 Provider、来源校验、来源回退、去重、事件聚合、24/48/72 小时窗口、热度解释、趋势图、任务滚动日志和来源审计字段。

当前实际边界：

- TrendCollector 的主路径是读取已监控账号近 72 小时的 live 作品样本，最多处理 500 条；这不是全网采集。
- 独立平台趋势目前明确实现的是 YouTube Data API；没有 API Key 时 YouTube 趋势跳过，TikTok/抖音/Bilibili 更多表现为“已监控样本不足”。
- 新闻中心虽然支持多种 Provider，但需要用户配置来源，尚未提供经过验证的体育媒体、赛事官网、球队/运动员官方源包和平台热门榜单的持续采集矩阵。
- 目前没有完整的跨平台实体归一化、事件级多语言聚类、来源数量置信度、内容可用性和热度增速的统一评分基线。

结论：**新闻聚合可用，用户要求的“全网 24–72 小时热点”尚未完成；这是产品核心范围的 P0/P1 缺口**。

### 3.6 自动化、通知与可靠性运维

已具备：自动化规则条件树、启停、编辑、动作绑定、冷却和去重；通知 Provider 注册、配置加密/脱敏、投递记录、重试、outbox、dead-letter、重放/丢弃和执行历史；最近已补充规则列表编辑列与启停按钮。

需要完善：

- 本轮和既有前端验收没有向真实第三方渠道发送成功 canary，真实 DNS、TLS、限流、第三方响应格式和重复投递仍未在生产凭证下验证。
- 缺少按渠道维度的成功率、P50/P95 延迟、重试次数、死信率、限流次数和最近一次健康探针面板。
- 规则执行依赖 Celery/Redis 单机部署，缺少多 worker 下的锁竞争、重复执行、任务漂移和 beat 双实例验证。
- 通知模板、规则、渠道和被监控实体之间的删除/停用语义需要统一软删除和引用完整性策略。

结论：**业务链路完整，外部投递可靠性和多 worker 并发仍需 P1**。

### 3.7 规则中心、内容生成、LLM 和语义检索

已具备：7.9 原文导入与结构化、版本/草稿/发布/对比/回滚、Prompt/Provider 抽象、多阶段生成工作流、审计、内容来源选择、视频内容检索和可选 pgvector 语义检索。

需要完善：

- 没有配置真实 LLM Provider 时生成按钮禁用是正确的，但也意味着生产生成能力当前不应被宣称为已验证。
- 生成质量缺少固定体育事实集、跨语言集、回归评测集、成本/Token/延迟预算和人工采纳率指标。
- 本地语义检索默认关闭，embedding 服务、模型、维度、索引回填和积压状态没有统一运维面板。
- `llm-experimental` 使用 g4f/网页转 API 路径，项目自身已标明不适合生产并可能违反第三方条款；生产配置必须显式禁用。

结论：**平台能力完整度较高，但生产 Provider、质量评测和合规边界是 P1/P0 运维项**。

### 3.8 认证、权限、安全与数据合规

已具备：密码哈希、登录限流、会话 token 哈希、CSRF、工作区角色、服务端权限校验、通知密钥加密/脱敏、新闻源 SSRF 检查、媒体路径穿越防护、请求 ID 和审计事件。

需要完善：

- Compose 默认是 development 环境，包含开发密钥、HTTP、`Secure=false` Cookie 和本地数据库密码；部署生产前必须强制环境校验并拒绝默认值。
- 翻译镜像和实验 LLM 使用浮动 `latest`，需要 digest pin、镜像扫描、SBOM 和依赖升级流程。
- 需要补充租户级数据导出/删除、凭证轮换、Cookie 过期告警、媒体保留期、日志脱敏审计和最小权限运维账户。
- Caddy 已有基础安全响应头，但生产 HTTPS、HSTS、备份加密、恢复演练和外部暴露面扫描尚未形成验收项。

结论：**内测安全基线较好，生产安全基线未闭环**。

### 3.9 数据库、任务和部署高可用

已具备：PostgreSQL + pgvector、Redis、Celery worker/beat、独立 subtitle worker、健康检查、迁移自动升级、outbox/dead-letter 和单机 Compose 启动。

需要完善：

- 当前 Compose 是单机单实例，API/worker/beat/Redis/PostgreSQL 没有跨主机冗余；宿主机或 Docker Desktop 故障会整体中断。
- worker/beat/subtitle-worker 没有独立健康探针和任务消费延迟指标；容器“运行中”不等于任务可消费。
- 数据库连接池、Redis 队列积压、Celery 活跃任务、失败任务、媒体磁盘和翻译模型磁盘没有统一容量/告警阈值。
- 尚未完成数据库备份恢复、Redis 数据恢复、媒体目录恢复和跨版本迁移演练。
- 当前工作树存在大量未提交修改，审计可复现性和回滚能力不足，应先建立可追溯发布提交与迁移包。

结论：**适合单机内测，不满足跨主机 HA 目标**。

## 四、按优先级的修复清单

### P0：生产前必须完成

1. 建立 Artifact Registry：每个视频、封面、info.json、原字幕、翻译字幕和导出文件记录状态、路径、大小、MIME、checksum、生成任务、源 URL、模型/版本和最后校验时间；UI 只依据校验后的 ready 展示“已下载/已生成”。
2. 建立同步调度器：实现账号租约、平台全局并发、平台/账号请求预算、代理/Cookie 隔离、优先级、队列长度和预计等待时间；把这些参数与运行日志、SLO 绑定。
3. 增加平台每日 canary：YouTube/TikTok/抖音/Bilibili 各一个公开样本，验证账号资料、总作品目录、第一页/第二页、封面、指标、字幕和错误分类；失败不写假数据并发出内部告警。
4. 修复 Ruff 2 个错误和正确目录下 mypy 的 67 个错误，至少先清理同步、下载、字幕、任务和适配器路径；将静态门禁加入 Docker/CI。
5. 将 API 617 个测试拆成并行分片，修复慢测试的数据库重建成本，形成“快速 PR 门禁 + 夜间全量门禁”；全量未通过前不宣称全项目测试通过。
6. 生产配置硬门禁：禁止默认 secret、默认数据库密码、HTTP/Secure=false Cookie、浮动镜像标签和实验 LLM；补充 HTTPS、密钥轮换和备份恢复演练。

### P1：提升产品核心价值和运营效率

1. 热点采集从“监控样本”扩展为 Source Adapter → Raw Item → Canonical Event → Dedup Cluster → Freshness/Heat Score → Alert/Report；首批接入赛事官网、球队/运动员官方源、主流体育媒体 RSS/Atom、YouTube 趋势、合规公开平台榜单和用户自定义源。
2. 评论增加 cursor、水位、批次、评论快照和点赞/回复增长；Top 20 与“增量评论”分开配置。
3. 字幕增加模型版本、语言覆盖率、质量抽检、CPU/GPU 预算、队列积压和缓存容量面板；对翻译轨道明确“机器翻译”来源并支持重试/取消。
4. 下载增加断点续传、部分成功重试、文件级状态、磁盘配额和自动清理；支持对象存储迁移而不改变前端媒体 URL 契约。
5. 通知增加真实 canary、渠道健康探针、成功率/延迟/死信率指标和渠道级限流；验证多 worker 幂等执行。
6. 为账号、作品、热点、字幕、通知建立统一导出和审计报告格式，字段级显示 observed/derived/requires_authorization/stale。

### P2：规模化扩展

1. API/worker/beat 多实例、Redis Sentinel/托管队列、PostgreSQL 高可用、对象存储和跨主机灾备。
2. 历史快照归档、分区和冷热数据策略；达到量级后再评估 ClickHouse/消息流系统，不提前引入复杂基础设施。
3. 竞品账号基准、最佳发布时间、团队审批、发布编排和跨平台发布回执；在监控/情报稳定后再做。
4. 多租户套餐、配额、计费和数据隔离；当前权限模型已具备基础，但还不是商业化配额系统。

## 五、建议验收门槛

达到生产发布前，至少满足：

- 连续 7 天平台 canary 有明确成功/失败分类；失败不产生空覆盖或假成功。
- 普通账号在预算内完成同步；长账号能分页续跑、暂停/取消/恢复，永不无限等待；同账号不会并发跑两个冲突任务。
- 作品和字幕所有 ready 状态都通过物理文件校验；删除、损坏、磁盘不足能在页面明确显示并可恢复。
- 同步成功率、部分成功率、降级率、平台限流率、队列等待时间、P95 外部调用耗时、媒体完整率、字幕翻译成功率和通知成功率均有历史指标。
- Ruff、mypy、快速 API 测试和 Web 测试在 CI 通过；夜间 API 全量测试稳定完成，不能继续以超时替代结果。
- 完成数据库、Redis、媒体目录、翻译模型和密钥恢复演练；默认开发密钥和实验 LLM 在生产启动时被拒绝。

## 六、最终判断

## 2026-08-15 Remediation update

The review above predates the latest remediation batch. The following items
are now implemented and supersede the corresponding open findings:

1. `MediaArtifact` plus the artifact registry migration verifies physical media
   files (safe relative path, regular file, non-zero size, MIME and SHA-256) and
   drives the frontend ready/disabled state from verified records.
2. Redis sync leases enforce bounded global and per-platform concurrency, with
   token-safe release and expiry recovery. Defaults are global `2`, per-platform
   `1`, wait `30s`, and Celery process concurrency `4`.
3. Comment collection is append-only at snapshot level. The current ranked Top
   20 view can change without deleting historical comments, and empty collection
   responses are non-destructive.
4. Hotspot collection has an independent public RSS/Atom path for the `web`
   dimension with a 72-hour freshness rule, bounded concurrent source fetches,
   provenance, confidence and explicit null unavailable metrics.
5. Content list/detail queries eagerly load artifact relationships, fixing the
   `MissingGreenlet` failure that appeared when sorting the works table.
6. Container Ruff and mypy are clean, migration head is `20260814_0002`, and
   Docker rebuild/deploy plus API/web health checks passed.

The test evidence is intentionally split: all API test files were executed in
module shards and passed; the merged 618-selected-test run exceeded the current
10-minute gate because the PostgreSQL fixture is expensive and the full run is
not claimed as passed. Real external platform canaries, live third-party
notification delivery, storage lifecycle/quota, production secret/image
pinning and cross-host HA/backup recovery remain release boundaries rather than
being represented by mock success.

系统现在最值得继续投入的是“账号同步正确性 + 任务可观测性 + 真实数据来源质量”，而不是继续增加页面数量。字幕、播放器、自动化、通知和规则中心已经有可用基础；下一阶段应围绕 P0 完整性验证、平台 canary、全局调度、热点独立采集和生产门禁收敛。完成这些后，再扩展更多平台、跨平台发布和商业化能力，风险最低、收益最高。
