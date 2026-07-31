# 安装与首次启动

Windows、Ubuntu/Debian、Fedora/RHEL 系和 macOS 可以直接使用 [跨平台一键安装脚本](ONE_CLICK_INSTALL.md)。以下步骤保留给需要逐项控制配置、迁移和种子数据的手动安装场景。

## 前置条件

- Docker Engine 或 Docker Desktop，支持 Docker Compose v2。
- 建议至少 4 核 CPU、8 GB 内存和 10 GB 可用磁盘。
- 首次构建需要访问 Docker Hub 与 npm/PyPI 软件源。

## 1. 准备配置

在仓库根目录执行：

```powershell
Copy-Item .env.example .env
```

至少设置管理员邮箱和一个不少于 12 个字符的随机密码：

```dotenv
SIO_BOOTSTRAP_ADMIN_EMAIL=admin@example.com
SIO_BOOTSTRAP_ADMIN_PASSWORD=replace-with-a-local-random-password
```

生产环境还必须替换 `POSTGRES_PASSWORD`、`SIO_SECRET_KEY`、`SIO_NOTIFICATION_ENCRYPTION_KEY`，设置 `SIO_ENVIRONMENT=production` 与 `SIO_SESSION_COOKIE_SECURE=true`。不要把 `.env` 提交到 Git。

## 2. 启动和迁移

```powershell
docker compose config
docker compose up -d --build
make migrate
make seed
```

没有 `make` 时使用：

```powershell
docker compose run --rm api sh -lc "cd apps/api && alembic upgrade head"
docker compose run --rm api python -m app.cli bootstrap-admin
```

`make seed` 没有默认密码；缺少两项 bootstrap 环境变量时会明确失败。

## 3. 初始化首期目录

```powershell
make seed-platforms
make seed-news-sources
make import-rules FILE=data/rules/ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt
make seed-generation
make seed-automations
```

可选的 `make seed-demo` 只生成显著标记为 `mock` 的演示数据。默认 RSS 示例保持停用，不会在初始化时下载文章。

## 4. 检查服务

```powershell
docker compose ps
docker compose logs --tail=100 api worker beat web
```

- 管理后台：<http://localhost:8080>
- API 存活：<http://localhost:8000/health/live>
- PostgreSQL/Redis 就绪：<http://localhost:8000/health/ready>

如需执行认证烟雾测试，先把登录凭证放入当前终端环境，再运行 `make smoke`。脚本不会打印密码。

## 5. 升级

升级前备份 PostgreSQL 数据卷，然后执行：

```powershell
docker compose build --pull
make migrate
docker compose up -d
```

迁移降级只用于经过验证的回滚窗口；不要直接删除数据卷。
