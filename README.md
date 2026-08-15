# Content Intelligence OS

Content Intelligence OS（内容智能生产平台）是面向内容创作者、运营团队和多平台账号管理者的内容情报与生产自动化系统，首期保留体育内容能力作为垂直工作区。

当前已进入第一次交付验收：账号、作品、新闻、事件、选题、内容创作、规则、自动化、通知、任务、日志和设置已经整合到统一中文后台；核心按钮连接真实后端 API。Prompt、模型参数和多阶段工作流由系统内部版本化管理，不要求创作者手工编排。外部平台、LLM 和通知渠道未配置真实凭证时会显示真实错误或显式 Mock 标记，不会用静态成功响应补齐功能。

## 功能截图占位

| 页面 | 截图占位 | 验收重点 |
| --- | --- | --- |
| 仪表盘 | `docs/images/dashboard.png`（待真实部署截图） | 实时统计、趋势、任务和来源标记 |
| 账号与作品 | `docs/images/monitoring.png`（待真实部署截图） | 同步、快照、排序、筛选和导出 |
| 规则编辑器 | `docs/images/rules.png`（待真实部署截图） | 原文、结构化规则、版本和 QA |
| 内容创作 | `docs/images/generation.png`（待真实部署截图） | 热门素材、规则预设、一键生成和结构化成品 |
| 自动化 | `docs/images/automation.png`（待真实部署截图） | 可视化条件、动作链和执行历史 |

占位路径不会伪装成已完成截图；应在目标部署通过验收后替换。

## 技术栈

- Web：Next.js 16、React 19、TypeScript、Tailwind CSS、TanStack Query/Table、Recharts、React Hook Form、Zod。
- API：Python 3.12、FastAPI、SQLAlchemy 2、Pydantic 2、Alembic。
- 数据与任务：PostgreSQL 17、Redis 7.4、Celery Worker/Beat。
- 接入：HTTPX、Feedparser、BeautifulSoup、统一 Adapter/Provider 注册表。
- 部署与质量：Docker Compose、Caddy、Pytest、Vitest、Ruff、Mypy、ESLint、Prettier。

## 快速启动

### 跨平台一键安装

安装器会检查或安装 Docker Compose v2、生成本地随机密钥、启动全部服务、初始化管理员、导入完整 7.9 规则，并验证 API 就绪状态。已有 `.env` 不会被覆盖，Demo/Mock 数据必须显式选择。

```powershell
# Windows 10/11
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

```bash
# Ubuntu/Debian/Fedora/RHEL/macOS
bash scripts/install.sh
```

操作系统支持范围、非交互参数、Docker Desktop 重启边界和故障处理见 [跨平台一键安装指南](docs/ONE_CLICK_INSTALL.md)。

前置条件：Docker Desktop 或其他支持 Docker Compose v2 的运行时。

```powershell
Copy-Item .env.example .env
docker compose up -d
```

首次启动会构建镜像并自动执行 Alembic 迁移。服务入口：

- 统一入口与管理界面：<http://localhost:8080>
- Next.js 直连入口：<http://localhost:3000>
- FastAPI 健康检查：<http://localhost:8000/health/live>
- FastAPI 开发文档：<http://localhost:8000/docs>

### 关键环境变量

| 变量 | 用途 | 必填边界 |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | PostgreSQL 密码 | 生产必换 |
| `SIO_SECRET_KEY` | 会话签名及开发回退加密材料 | 生产必须独立随机值 |
| `SIO_NOTIFICATION_ENCRYPTION_KEY` | 通知渠道配置加密 | 生产必填 |
| `SIO_BOOTSTRAP_ADMIN_EMAIL/PASSWORD` | 首个管理员初始化 | 初始化时必填，无默认密码 |
| `SIO_YOUTUBE_API_KEY` | YouTube Data API v3 | 真实 YouTube 同步必填 |
| `SIO_LLM_OPENAI_COMPATIBLE_BASE_URL/API_KEY` | OpenAI 兼容 LLM | 真实模型调用必填 |
| `SIO_TASK_STALE_AFTER_SECONDS` | Worker 失联执行租约 | 默认 2100，不应短于任务硬时限 |
| `SIO_DATABASE_POOL_SIZE/MAX_OVERFLOW` | 每进程数据库连接池 | 按 API/Worker 副本数核算总连接数 |
| `SIO_REDIS_MAX_CONNECTIONS` | 每个 API 进程的 Redis 连接池上限 | 默认 50 |
| `SIO_AUTH_LOGIN_MAX_ATTEMPTS_PER_IDENTITY/IP` | 数据库共享登录限流 | 默认 10/100，身份与 IP 只存 HMAC 哈希 |

完整说明与生产约束见 [.env.example](.env.example)、[设置中心说明](docs/SETTINGS_CENTER.md) 和 [安装指南](docs/INSTALLATION.md)。

### 初始化首个管理员

`.env.example` 不包含默认管理员密码。复制为 `.env` 后填写以下两项：

```dotenv
SIO_BOOTSTRAP_ADMIN_EMAIL=admin@example.com
SIO_BOOTSTRAP_ADMIN_PASSWORD=
```

然后执行：

```powershell
docker compose run --rm api python -m app.cli bootstrap-admin
```

也可使用 `make seed`。命令不会打印或把明文密码写入代码；重复邮箱不会被用于静默重置密码。完成初始化后建议从环境配置中移除 bootstrap 密码。

初始化平台目录；如需演示，再单独创建显著标记的 Mock 数据：

```powershell
docker compose run --rm api python -m app.cli seed-platforms
docker compose run --rm api python -m app.cli seed-demo-monitoring
docker compose run --rm api python -m app.cli seed-news-sources
docker compose run --rm api python -m app.cli seed-automations
```

第二条命令生成的所有账号、作品、快照与指标均标记为 `source_kind=mock`。第三条只创建三个默认停用的官方 RSS 配置示例和一个空手动来源，不下载或内置任何新闻文章。

### 导入 7.9 规则

仓库已保存本次由用户提供的完整源文件。完成迁移和管理员初始化后执行：

```powershell
make import-rules FILE=data/rules/ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt
```

没有 `make` 时使用：

```powershell
docker compose run --rm api python -m app.cli import-rules --file data/rules/ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt
```

当前完整文件 SHA-256 为 `9f69ee764fc9c33217699df584bba18ecd5d584af8ada3770e5c8779f9e824d6`。导入生成 816 个章节节点和 1,021 条结构化规则；相同哈希重复导入不会创建重复版本。登录后访问 `/rules`。解析器不会凭空补写原文没有明确给出的 Why、How 或单规则 QA，这些缺失会作为可见验证警告保留。详见 [规则导入指南](docs/RULE_IMPORT_GUIDE.md)。

### 初始化 Prompt 与生成工作流

完整 7.9 规则发布后，创建首个已发布 Prompt 和默认引用该规则版本的十步工作流：

```powershell
make seed-generation
```

没有 `make` 时执行：

```powershell
docker compose run --rm api python -m app.cli seed-generation
```

Mock LLM 无需密钥，但输出始终带 `MOCK TEST OUTPUT`、`source_kind=mock` 和测试标签。真实 OpenAI 兼容接口仅从 API/Worker 后端环境读取配置：

```dotenv
SIO_LLM_OPENAI_COMPATIBLE_BASE_URL=https://provider.example/v1
SIO_LLM_OPENAI_COMPATIBLE_API_KEY=
SIO_LLM_DEFAULT_MODEL=gpt-5.6-terra
```

浏览器不会获得明文 Key。Owner/Admin 可在“设置 → LLM API”按工作区加密保存 Base URL、Key、Organization/Project、自定义 Header、模型、采样、Token、超时、重试和成本参数。创作者登录后只需进入 `/generate`，选择热门视频、新闻、聚合事件或自定义材料，再选择规则预设即可生成；`/generations` 以英文 TTS、翻译、标题、关键词、素材词和 QA 卡片展示成品。Prompt 和十步工作流仍在后端版本化、固定到每次运行并可审计，但不出现在主导航或日常创作表单中。没有独立研究证据时，运行会保持 `verification_incomplete`，不会让 LLM 自称完成联网核实。详见 [生成工作流指南](docs/GENERATION_WORKFLOW.md)。

通知渠道凭证只在后端加密保存。生产环境必须配置独立的 `SIO_NOTIFICATION_ENCRYPTION_KEY`；三个内置示例自动化默认停用，绑定渠道并检查后才能启用。订阅告警可在“设置 → 订阅告警”按新作品、关键词或指标突变触发统一通知队列，详见 [自动化与通知指南](docs/AUTOMATION_NOTIFICATIONS.md) 和 [订阅告警](docs/SUBSCRIPTION_ALERTS.md)。

媒体文件的物理完整性、配额和生命周期治理见 [媒体存储生命周期治理](docs/STORAGE_LIFECYCLE.md)。默认只读预览，自动删除必须由 Owner/Admin 显式确认并启用策略；不会把数据库中的文件名当作真实文件存在。

### 添加 RSS 新闻源

登录后进入“设置 → 新闻源”，新增 `rss` 或 `atom` 来源并启用，然后手动同步。来源 URL 必须是合法公开地址；系统拒绝直接私网目标，不会抓取文章链接页全文。发布时间缺失时保持为空，不使用抓取时间冒充。默认 RSS 示例均为停用配置。

### 配置通知渠道

进入“设置 → 通知 Provider”或“通知渠道”，选择 Email、Generic Webhook、Telegram、Discord、飞书、钉钉或企业微信。页面按 Provider 契约展示 SMTP/TLS、Header/HMAC、Parse Mode、@成员、超时和重试等专属细项；凭证提交到本系统后端并加密保存，前端只看到脱敏摘要。真实测试通知发送前会再次确认；未配置渠道或外部失败不会显示成功。扩展细节见 [通知 Provider 指南](docs/NOTIFICATION_PROVIDER_GUIDE.md)。

### 配置 YouTube 官方 API

在 Google Cloud 启用 YouTube Data API v3 后，将 API Key 仅写入本地 `.env`：

```dotenv
SIO_YOUTUBE_API_KEY=
```

留空时 YouTube 同步会记录明确的配置错误，不会静默切换为 Mock。系统目前只获取公开频道、上传作品和公开统计；YouTube Analytics API 的流量来源、留存、收入、搜索词等私有字段尚未实现，也不会伪造。

登录后可调用 `POST /api/v1/accounts/{id}/sync` 手动排队，并通过 `GET /api/v1/accounts/{id}/sync-runs` 或 Dashboard 查看最近状态、错误和下一同步时间。

## 视频内容搜索

`/video-search` 是基于视频内容证据的定时搜索闭环：先按平台发现候选 URL，再由视频分析器读取画面、动作、音频、语音转写与 OCR；只有包含有效起止时间戳和匹配依据的候选才会进入默认命中结果。标题、简介、标签、作者和 URL 只用于定位视频，不能单独形成命中。

部署与配置：

- 默认 `SIO_VIDEO_SEARCH_ANALYZER=none`，只记录真实候选，不伪造内容命中。
- 配置 `SIO_VIDEO_SEARCH_ANALYZER=gemini_video` 与 `SIO_GEMINI_API_KEY` 后，公开 YouTube 可直接交给 Gemini；公开 Bilibili、TikTok、抖音候选会在允许域名内由 yt-dlp 材料化后通过 Gemini Files API 分析。
- Docker 后端镜像包含 Node.js、yt-dlp、yt-dlp EJS 和 ffmpeg；分析上传大小由 `SIO_VIDEO_SEARCH_MAX_UPLOAD_BYTES` 限制，临时媒体在分析后清理。
- TikTok、抖音的候选搜索仍受平台公开搜索、反爬和登录墙限制；失败会记录为不可用/部分完成，不会显示为真实命中。完整数据边界与扩展路线见 [视频内容搜索可行性报告](docs/VIDEO_CONTENT_SEARCH_FEASIBILITY.md) 和 [技术说明书](docs/VIDEO_CONTENT_SEARCH_TECHNICAL_SPEC.md)。

## Monorepo 结构

```text
apps/
├── web/       Next.js 管理界面与服务端路由保护
├── api/       FastAPI、SQLAlchemy、Alembic、共享后端模块
└── worker/    Celery Worker/Beat 组合入口
packages/
├── shared-types/
├── ui/
└── config/
deploy/        API/Web Dockerfile 与 Caddy 配置
scripts/       本地开发和离线验证脚本
tests/         仓库治理与基础设施契约测试
```

前端只访问本系统 API，不持有或直连第三方平台、LLM 或通知凭证。平台、新闻、LLM 和通知均通过 Adapter/Provider 边界接入。

## 常用命令

```text
make dev       前台构建并启动全部服务
make up        后台构建并启动全部服务
make down      停止服务（保留数据卷）
make logs      跟踪服务日志
make migrate   执行 Alembic 升级
make seed      初始化首个管理员
make seed-platforms  初始化平台目录
make seed-demo  创建显著标记的 Demo/Mock 账号与作品
make seed-news-sources  创建默认停用的 RSS 配置示例和空手动来源
make import-rules FILE=...  导入并发布完整 7.9 规则原文
make seed-generation  创建版本化 Prompt 和十步生成工作流
make seed-automations  创建三个默认停用的自动化示例
make test      运行后端与前端测试
make lint      运行 Ruff、Mypy、ESLint 与 TypeScript 检查
make format    格式化 Python 与前端代码
```

Windows 未安装 `make` 时可以直接使用对应的 `docker compose` 命令；`scripts/dev.ps1` 和 `scripts/check.ps1` 分别提供启动及本机质量检查入口。

## 不使用 Docker 的本地开发

需要 Python 3.12、Node.js 24、pnpm 11，以及可访问的 PostgreSQL 和 Redis：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
pnpm install --frozen-lockfile
Copy-Item .env.example .env

Push-Location apps\api
..\..\.venv\Scripts\python.exe -m alembic upgrade head
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
Pop-Location
```

另开终端执行 `pnpm dev`。Worker 与 Beat 分别使用：

```powershell
.\.venv\Scripts\celery.exe -A apps.worker.celery_app:celery_app worker --loglevel=INFO --queues=maintenance,monitoring,news,generation,automation,notification
.\.venv\Scripts\celery.exe -A apps.worker.celery_app:celery_app beat --loglevel=INFO
```

## 认证与安全基线

- 密码使用 Argon2 哈希。
- 登录签发随机不透明会话令牌；数据库只保存令牌哈希，浏览器 Cookie 为 HttpOnly、SameSite=Lax。
- 写操作使用 CSRF Token；退出会撤销服务端会话。
- `/api/v1/me` 和管理后台由服务端会话保护。
- 生产配置会拒绝开发 Secret、开发数据库密码和非安全 Cookie。
- 密钥、Token、Cookie 和密码不得提交到仓库。

Docker Compose 默认值只用于本地开发。生产环境必须设置 `SIO_ENVIRONMENT=production`、独立的 `SIO_SECRET_KEY`、数据库强密码、`SIO_SESSION_COOKIE_SECURE=true`，并配置正式 TLS 入口。

## 验证

```powershell
# 后端
Push-Location apps\api
..\..\.venv\Scripts\python.exe -m ruff check --no-cache app tests
..\..\.venv\Scripts\python.exe -m mypy app
..\..\.venv\Scripts\python.exe -m pytest
Pop-Location

# 前端
pnpm typecheck
pnpm lint
pnpm test
pnpm format:check

# 仓库契约与 Compose 静态结构
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\validate_compose.py docker-compose.yml
```

具备 Docker 的环境还必须运行：

```powershell
docker compose config --quiet
```

完整 Compose 启动后可设置 `SIO_ACCEPTANCE_EMAIL` 和 `SIO_ACCEPTANCE_PASSWORD`，运行 `make smoke` 检查 Web、健康探针、登录和核心只读 API。Worker/Beat 仍需结合 `docker compose ps` 与任务记录确认。

## 数据真实性边界

手动登记账号和文章标记为 `imported`，实时 Provider 标记为 `live`，Mock Adapter 与 Demo 种子固定标记为 `mock`。本地 Docker 已使用真实 RSS、真实 Bilibili 历史作品和由这些作品派生的趋势数据完成验收；TikTok Token 无效、YouTube 缺少 Key、抖音上游响应异常和 Bilibili 登录墙仍保留真实失败，不能宣称成功。趋势热度与高潜分均标记为派生指标。真实 LLM 与外部通知渠道仍因缺少凭证未执行可计费或真实发送验证。详见 [平台同步](docs/PLATFORM_SYNC.md)、[真实数据验收](docs/REAL_DATA_ACCEPTANCE.md)、[新闻聚合](docs/NEWS_AGGREGATION.md)、[规则导入指南](docs/RULE_IMPORT_GUIDE.md) 与 [自动化通知](docs/AUTOMATION_NOTIFICATIONS.md)。

阶段完成情况、验证记录、已知限制和下一阶段入口见 [docs/STATUS.md](docs/STATUS.md)。指标公式与可信度见 [数据指标口径目录](docs/METRIC_CATALOG.md)，仍待处理的外部授权和产品任务见 [待处理任务清单](docs/NEXT_TASKS.md)。成熟产品对标、功能差距与第二阶段优先级见 [行业对标与产品优化建议](docs/INDUSTRY_BENCHMARK_AND_OPTIMIZATION.md)。

## 常见问题

### 系统有默认管理员密码吗？

没有。必须在本地环境中设置 bootstrap 邮箱和密码后执行 `make seed`；初始化完成后应移除 bootstrap 密码。

### 没有 YouTube 或 LLM Key 能否使用？

可以使用已配置的真实 RSS、合规公开页、加密自动登录/授权会话或显式 Mock 垂直链路；每条记录保留来源标记。YouTube 不会在缺少 Key 时自动切到 Mock，LLM 未配置时生成结果会明确标记为测试输出。

### 为什么 RSS 文章没有发布时间？

来源没有提供可靠发布时间时系统保留空值，以避免把抓取时间伪装成发布时间。

### 为什么 Mock 数据没有触发通知？

Mock 默认被生产自动化阻止；仅测试模式或规则明确允许 Mock 时才会执行，记录仍标记为 `mock`。

更多排查见 [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

## 当前限制

- YouTube Analytics OAuth 私有指标尚未实现；TikTok Display、抖音开放平台与全平台浏览器 Adapter 已实现，但部分真实凭证仍未通过验收。
- 新闻事件聚类为标题相似度基础版本，尚无跨语言向量或通用联网研究工具。
- OpenAI 兼容 Provider 支持流式预览；真实可计费调用需要用户配置并单独验收。
- 自动化仍采用周期扫描；Outbox、外部调用尝试和死信重放/丢弃已提供审计与人工恢复入口。
- 单机 Compose 是首期部署目标，尚未提供跨主机高可用。

## 后续路线图

第二阶段建议优先完成各平台有效凭证验收与 Analytics OAuth、趋势异常解释和跨平台同题聚类、研究检索与事实证据、新闻跨语言聚类、服务端保存视图及持续浏览器 E2E。路线图见 [ROADMAP.md](docs/ROADMAP.md)。

## 文档索引

[安装](docs/INSTALLATION.md) · [开发](docs/DEVELOPMENT.md) · [部署](docs/DEPLOYMENT.md) · [设置中心](docs/SETTINGS_CENTER.md) · [平台采集](docs/PLATFORM_SYNC.md) · [真实数据验收](docs/REAL_DATA_ACCEPTANCE.md) · [指标口径](docs/METRIC_CATALOG.md) · [待处理任务](docs/NEXT_TASKS.md) · [平台 Adapter](docs/PLATFORM_ADAPTER_GUIDE.md) · [新闻 Provider](docs/NEWS_PROVIDER_GUIDE.md) · [LLM Provider](docs/LLM_PROVIDER_GUIDE.md) · [通知 Provider](docs/NOTIFICATION_PROVIDER_GUIDE.md) · [订阅告警](docs/SUBSCRIPTION_ALERTS.md) · [规则导入](docs/RULE_IMPORT_GUIDE.md) · [自动化](docs/AUTOMATION_GUIDE.md) · [故障排查](docs/TROUBLESHOOTING.md)
