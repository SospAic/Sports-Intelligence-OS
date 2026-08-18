# 部署与运维

## Compose 拓扑

`proxy → web/api`，API 使用 PostgreSQL 与 Redis；Worker 消费 maintenance、monitoring、news、generation、automation、notification 队列；Beat 负责周期调度。首期是单机 Compose，不包含跨主机高可用。

## 生产环境必填

```dotenv
SIO_ENVIRONMENT=production
POSTGRES_PASSWORD=<strong-random-password>
SIO_SECRET_KEY=<independent-random-secret>
SIO_NOTIFICATION_ENCRYPTION_KEY=<independent-32+-char-secret>
SIO_SESSION_COOKIE_SECURE=true
SIO_TASK_STALE_AFTER_SECONDS=2100
```

在公网暴露前配置正式域名、TLS、可信反向代理和最小化 CORS。数据库与 Redis 端口默认只绑定 `127.0.0.1`，不要直接暴露到公网。

## 部署

```bash
docker compose config --quiet
docker compose build --pull
docker compose up -d
docker compose ps
```

API 启动会升级迁移，正式变更窗口仍建议先显式执行 `make migrate`。管理员初始化完成后，从运行环境移除 bootstrap 密码。

## 健康和恢复

- `/health/live` 只说明 API 进程存活。
- `/health/ready` 同时检查数据库和 Redis。
- `docker compose ps` 检查 Worker、Beat 和 Web；它们没有业务成功的替代含义。
- 同步、新闻、生成、自动化和通知失败记录保存在各自运行表中，可从后台任务/日志页面查询。
- 订阅告警迁移会创建 `subscription_rules`、`subscription_events` 并将通知投递关联到订阅；部署后先执行迁移，再在「设置 → 订阅告警」绑定启用的通知渠道。详见 [订阅告警](SUBSCRIPTION_ALERTS.md)。
- Celery 任务有 1,800 秒软限制和 1,860 秒硬限制；默认 2,100 秒租约只用于确认 Worker 已失联后释放锁或失败状态，不能设置得短于正常最大任务时间。

## 备份

至少备份 PostgreSQL；Redis 是队列与短期状态，不应是唯一业务事实来源。备份必须包含通知配置加密密钥，否则加密渠道配置无法恢复。恢复后先运行迁移与只读健康检查，再开放写流量。

媒体目录也必须纳入备份或明确声明为可重新下载。生命周期清理默认关闭，启用前必须先执行预览和受控恢复演练；具体保留级别、孤儿文件边界和审计字段见 [STORAGE_LIFECYCLE.md](STORAGE_LIFECYCLE.md)。仓库提供 `scripts/backup_restore_drill.py`，使用隔离的临时数据库名验证 PostgreSQL dump、Redis RDB 和媒体归档，不删除应用数据卷。

生产启动前运行 `python scripts/validate_production_config.py`。它会拒绝默认密钥、开发数据库密码、非 Secure Cookie、实验 LLM 回退、无配额的自动媒体清理和浮动翻译镜像标签。跨主机 HA、托管 Redis/PostgreSQL、对象存储和灾备切换仍需部署环境完成，不能由本地 Compose 验收替代。

## 扩容边界

可增加 Worker 副本，但 Beat 保持单实例；账号锁、通知幂等键和冷却状态位于数据库。首期没有消息总线级事件流、死信队列或跨区域复制，达到相关容量前应先测量而不是直接引入重型组件。
## yt-dlp / Node.js 运行时

API、Worker 与 Beat 镜像内置 Node.js 22，并安装 `yt-dlp[default]` 及其 EJS 组件。Docker Compose 默认将 `SIO_YTDLP_NODE_PATH` 设为 `/usr/local/bin/node`。宿主机直接运行 API 时可留空让程序从 `PATH` 查找，或填入 Node 可执行文件绝对路径。

```env
SIO_YTDLP_NODE_PATH=
SIO_YTDLP_REMOTE_COMPONENTS=
SIO_YTDLP_ALLOW_RUNTIME_UPDATE=false
```

`SIO_YTDLP_REMOTE_COMPONENTS` 仅接受 `ejs:github` 或 `ejs:npm`，用于镜像没有匹配 EJS 包时的显式远程补充。运行时更新默认关闭；生产环境请修改依赖后重建 API/Worker/Beat 镜像，避免在容器内临时安装的版本随重启丢失。YouTube 返回 HTTP 429 时属于平台限流，Node.js 不能解除该限制；下载页会尝试使用公开 oEmbed 补齐预览元数据，但字幕和媒体仍以异步任务最终结果为准。

### yt-dlp 浏览器鉴权

设置页的「同步设置 → 登录与鉴权」提供 `--cookies-from-browser` 下拉选择。系统只保存浏览器名称，不保存、导出或回传 Cookie 内容；实际 Cookie 由执行 yt-dlp 的 API/Worker 进程在运行时读取。

Docker 部署时，容器默认看不到宿主机的浏览器配置目录。若要使用该选项，需要把获得授权的浏览器 profile 以只读方式挂载到 API 和 Worker，并确保容器内运行用户有读取权限；仅在设置页选择浏览器而不挂载 profile 会导致 yt-dlp 报“无法读取浏览器 Cookie”。选择“匿名”即可恢复无 Cookie 的公开抓取。

该选项只能使用用户已经拥有的登录会话，不能绕过验证码、登录墙或平台访问限制，也不能保证消除 429。yt-dlp 当前支持的浏览器名称以其官方 `--help` 为准；项目下拉框覆盖 `brave/chrome/chromium/edge/firefox/opera/safari/vivaldi/whale`。

### 人工登录并保存 Cookie

Docker Compose 已内置一个带可视化 Chromium 的 `browser` 服务。点击设置页「平台管理 →
加密会话状态 → 打开平台登录页」时，API 会在该容器内创建平台登录页，并自动打开本机
noVNC 窗口；不再需要先在宿主机安装或启动 Chrome/Edge：

1. 执行 `docker compose up -d browser api worker beat web`；默认参数包括 `DISPLAY=:99`、
   Xvfb `1440x900x24`、Chromium 上游 CDP `--remote-debugging-port=9223`、
   `--remote-debugging-address=0.0.0.0`、`--remote-allow-origins=*`、专用 profile、
   `--disable-dev-shm-usage`、`--disable-gpu`、`--no-sandbox`，以及只在 Compose 内网提供的
   CDP 代理 `9222` 和 noVNC `6080` 端口。
2. 平台卡片的 CDP 地址默认是 Docker 内部地址 `http://browser:9222`，通常不需要修改。
3. 点击「打开平台登录页」，系统会打开 `http://localhost:6080/vnc.html`，在其中人工完成
   登录、验证码和二次验证。
4. 回到设置页确认授权条件，点击「保存已登录 Cookie」。

`browser` 服务不把 CDP `9222` 映射到宿主机，只把 noVNC 绑定到
`127.0.0.1:6080`；专用 profile 持久化在 Docker volume `docker_browser_profile`。
如果必须改端口，可在 `.env` 中调整 `SIO_BROWSER_CDP_PORT`、`SIO_BROWSER_CHROME_CDP_PORT`、
`SIO_BROWSER_VNC_PORT`、`SIO_BROWSER_CDP_ENDPOINT` 和 `SIO_BROWSER_VNC_URL`，然后重新构建/启动服务。

宿主机 Chrome/Edge 仍作为备用方案：使用专用 profile 启动
`--remote-debugging-port=9222`，Docker API 连接地址填写
`http://host.docker.internal:9222`。不要使用个人主 profile，也不要把 CDP 端口暴露到公网。

服务端只读取当前平台域名的 Cookie，并将 Playwright 会话状态与 Netscape Cookie
文件内容加密保存；接口不会回传 Cookie 或密码。yt-dlp 任务执行时只在临时目录
生成一次性 Cookie 文件，子进程结束后立即删除。CDP 地址仅允许本机或 Docker
内置 `browser` 服务或主机网关，禁止用它连接任意远程地址。遇到验证码、二次验证或平台安全挑战时，
必须由用户在浏览器中完成，系统不会绕过。
