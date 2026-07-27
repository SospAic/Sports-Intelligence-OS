# 项目状态

更新时间：2026-07-26

## 当前阶段

**Prompt 11：最终代码审查与修复 — 已完成**

Prompt 10 与 Prompt 11 已严格按顺序完成。最终审查没有增加产品范围；修复集中在外部 URL 安全、派生指标正确性、自动化正则安全、7.9 答案词 QA、任务超时和失联执行租约。测试没有被删除或放宽；外部链路仍只使用显式 Mock 或去敏本地响应。

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

## 验证状态

| 验证项 | 结果 |
| --- | --- |
| 后端 Ruff | 通过，应用、测试及验证脚本无错误 |
| 后端 Mypy strict | 通过，120 个源文件无错误 |
| 后端 Pytest | 通过，52 项测试；另有 1 条上游 TestClient/httpx 弃用警告 |
| 仓库与验收脚本测试 | 通过，35 项测试（含安装器、Compose 配置传播与 URL 安全回归） |
| 前端 TypeScript | 通过，3 个工作区包完成检查 |
| 前端 ESLint | 通过 |
| 前端 Vitest | 通过，25 项测试 |
| Prettier | 通过 |
| Next.js production build | 通过，静态页面生成 22/22，动态路由编译成功 |
| 本地 HTTP 冒烟 | FastAPI 健康检查与 Next 登录页均返回 200 |
| 浏览器可视化点击 | 通过本地登录后的设置中心与一键内容创作验收：素材、规则、LLM 配置和通知字段均由真实 API 驱动 |
| Alembic | 临时 SQLite 完成 0001 → 0010 升级，并核对 40 张表；模型与迁移契约通过 |
| Compose 静态校验 | 通过，7 个服务、4 个健康检查、依赖门与数据卷符合约束 |
| `docker compose config --quiet` | 本机未安装 Docker CLI，无法执行；CI 已配置为强制执行 |

本机也没有 `make`，因此 Make 目标通过静态契约检查；各目标所调用的底层命令已分别验证。PostgreSQL 容器上的迁移和整套 Compose 启动仍需在具有 Docker 的环境由 CI 或开发者复核，不能把 SQLite 迁移测试描述为 PostgreSQL 实机验证。

## 数据真实性声明

YouTube 官方 Data API Adapter 已实现，但本机没有 API Key，真实调用未验证。新闻 Provider 已实现，但自动化测试只使用本地去敏 RSS/Atom/JSON 响应；默认外部 RSS 示例保持停用，未主动下载真实新闻。Feed 文章契约标记 `live`，手动文章标记 `imported`，Mock 监控数据标记 `mock`；事件收藏形成的选题标记为 `aggregated` 派生数据，不冒充原始实时来源。7.9 原文来自用户提供的本地文件，完整哈希与副本一致；结构化数据来自确定性解析，不以生成内容补齐缺失字段。真实 OpenAI 兼容 Provider 已实现但本机没有 Key，未执行真实或可计费调用；自动化测试只使用带 `MOCK TEST OUTPUT`、`source_kind=mock` 的 Mock LLM。用户文本标记 `imported`，无独立证据时保持 `verification_incomplete`。Email、Webhook、Telegram、Discord、飞书、钉钉和企业微信 Provider 已实现，但本机无真实渠道凭证，未执行真实发送；测试通知只使用 `mock_notification` 并显式记录 Mock 回执。

## 已知限制与尚未实现

- YouTube Analytics API 的 OAuth 私有分析、Comments 和配额预算尚未实现；TikTok、抖音、Bilibili 仍是骨架。
- 新闻聚类首期仅使用标题相似度；实体抽取、跨语言向量、文章修订历史、自动时间线、正文抓取、搜索/社交/视频热点源尚未实现。
- URL 在请求前会解析并拒绝非公网地址；生产环境仍建议使用固定出站代理、网络 ACL 和 DNS 策略形成第二道边界。
- 7.9 确定性解析保留 826 项缺少独立 QA 的警告；Why/How、示例、适用范围及规则关系只在原文明示时填充，进一步人工语义整理尚未完成。
- 当前规则树一次加载完整版本；数万规则规模的章节懒加载和虚拟滚动尚未实现。
- Research 首期只使用已持久化输入和来源，未实现通用联网搜索工具；OpenAI 兼容 Provider 暂不支持流式响应或厂商专有能力。
- 自动化首期为 30 秒级近实时扫描，不是消息总线级实时；完整 Outbox 消费、每次网络尝试独立表和通知模板版本管理尚未实现。
- 全局搜索首期只覆盖页面/功能入口；服务端保存列布局、跨域全文检索和大数据量专用仪表盘聚合尚未实现。
- 已具备 SQLite 隔离的 API/领域测试、React 组件测试和完整 Mock 垂直链路；PostgreSQL/Redis 容器集成与浏览器实机验收因本机无 Docker 仍需在具备容器运行时的环境执行。
- 完整 Outbox 消费仍未实现；任务失联租约和过期会话定时清理已实现，但独立死信表和每次外部尝试明细仍待第二阶段。

## 阶段结论

Prompt 00–11 已按顺序完成，第一次交付代码阶段结束。下一步不是继续增加首期功能，而是在具备 Docker Compose v2 和用户测试凭证的目标环境执行 `docs/FIRST_DELIVERY_REPORT.md` 中的实机验收；仍不把 SQLite、Mock 或静态 Compose 校验描述成 PostgreSQL/Redis/真实平台成功。

## 2026-07-26 本地运行与行业对标补充

- 当前 Windows 主机仍未安装 Docker/Podman、PostgreSQL、Redis、Make 和 GitHub CLI；因此不能执行完整 Compose、Worker 或 Beat 实机验收。
- 使用独立 SQLite 开发数据库完成 0001–0010 迁移，并初始化本地管理员、平台目录、显式 Demo/Mock 监控数据、停用的新闻源示例、完整 7.9 规则、默认 Prompt/工作流和停用的自动化示例。
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
- 当前全量结果：后端 52 项、前端 25 项、仓库契约 35 项测试通过；Ruff、Mypy strict（120 个源文件）、TypeScript、ESLint、Prettier、Next.js 生产构建和 Compose 静态校验通过；迁移 0001–0010 共 40 张表通过临时 SQLite 验证。

## 2026-07-27 内容创作流程收敛

- 创作者主流程收敛为“热门视频/新闻/事件或自定义材料 → 规则预设 → 一键生成 → 结构化成品”，不再要求选择 Prompt 版本、工作流、Provider、模型或采样参数。
- 系统可以稳定识别 7.9 规则所需输入和输出：输入侧保留素材、规则、成片长度、答案词与创作备注；输出侧固定展示事实摘要、来源、故事价值、英文 TTS、中文翻译、中英文标题、搜索词、素材词、标签、工程文件名与 QA。
- Prompt 中心已从主导航和全局搜索移除；已发布 Prompt、工作流和模型参数仍由后端作为内部编排与不可变审计依据保存，没有删除既有版本、运行记录或自动化调用能力。
- `/generate` 直接读取真实作品、新闻和事件 API 并按热度/播放量展示；空状态、失败重试和 Mock 标识均保留。`/generations` 改为内容成品库，技术步骤、Prompt/模型和 Token 信息只在成品详情的折叠审计区展示。
- 修复创作者填写的答案词未进入冻结输入的问题；现在只接收有长度和范围约束的 `answer_word`、`answer_reveal_min_ratio` 与 `creator_brief`，数据库中的来源标题和事实仍不可被请求载荷覆盖。
- 本地登录后的浏览器验收通过：主导航不再出现 Prompt 中心，四类素材入口、规则预设、一键生成状态和 Mock 警告正常，页面控制台无错误。本机没有真实 LLM Key 和 Redis，未把 Mock 生成或后台任务降级描述为真实生成成功。
