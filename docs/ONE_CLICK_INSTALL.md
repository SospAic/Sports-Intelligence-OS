# 跨平台一键安装

本项目提供 Windows、Ubuntu/Debian、Fedora/RHEL 系、macOS 的安装入口。脚本会检查 Docker Compose v2，在支持的平台上安装缺失的 Docker 运行时，然后完成项目配置、镜像构建、数据库迁移、管理员初始化、7.9 规则导入以及服务健康验证。

脚本只在当前仓库目录内创建 `.env` 和 `.sio/` 状态文件，并启动 `docker-compose.yml` 声明的容器。它不会写入真实 YouTube、LLM 或通知凭证，不会主动抓取默认 RSS 示例，也不会默认生成 Demo 数据。

## 支持范围

| 操作系统 | 安装入口 | Docker 安装来源 | 说明 |
| --- | --- | --- | --- |
| Windows 10/11 | `scripts/install-windows.ps1` | Docker Desktop / winget | 需要满足 WSL 2 与 Docker Desktop 的系统要求；首次启动可能要求确认许可或重启 |
| Ubuntu、Debian | `scripts/install.sh` | Docker 官方 apt 仓库 | 需要 root 或 sudo；使用 Compose v2 插件 |
| Fedora、RHEL | `scripts/install.sh` | Docker 官方 dnf 仓库 | 需要 root 或 sudo |
| Rocky Linux、AlmaLinux | `scripts/install.sh` | Docker CentOS 仓库 | 兼容路径为 best effort，应在目标版本上复核 |
| macOS | `scripts/install.sh` | Homebrew Docker Desktop cask | 首次启动可能要求用户确认 Docker Desktop 条款 |

安装器遵循 Docker 的官方安装边界：[Windows](https://docs.docker.com/desktop/setup/install/windows-install/)、[macOS](https://docs.docker.com/desktop/setup/install/mac-install/)、[Ubuntu](https://docs.docker.com/engine/install/ubuntu/)、[Debian](https://docs.docker.com/engine/install/debian/)、[Fedora](https://docs.docker.com/engine/install/fedora/)、[RHEL](https://docs.docker.com/engine/install/rhel/) 与 [Compose v2](https://docs.docker.com/compose/install/linux/)。应以 Docker 当前列出的受支持系统版本为准。

## Windows

在项目根目录打开 PowerShell。首次安装 Docker Desktop 时可能出现 UAC、WSL 更新、许可确认或重启，这些系统边界无法安全静默绕过。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

脚本未收到密码时会生成一次性随机管理员密码，并仅在成功结束时显示。若要显式设置管理员与工作区：

```powershell
.\scripts\install-windows.ps1 `
  -AdminEmail "owner@example.com" `
  -WorkspaceName "Sports Studio"
```

仅在确实需要演示账号和作品时显式启用：

```powershell
.\scripts\install-windows.ps1 -WithDemoData
```

通过参数传入密码可能进入 PowerShell 历史，因此建议省略 `-AdminPassword` 并使用脚本生成的密码。已经自行安装并启动 Docker Desktop 时，可以增加 `-SkipDockerInstall`。

## Ubuntu、Debian、Fedora 与 RHEL 系

```bash
bash scripts/install.sh
```

安装 Docker 时脚本会请求 sudo。安装器不会自动把当前用户加入 `docker` 组，因为该组拥有接近 root 的主机权限；本次安装需要时会通过 sudo 调用 Docker。

自定义管理员或显式添加 Mock 数据：

```bash
bash scripts/install.sh \
  --admin-email owner@example.com \
  --workspace-name "Sports Studio" \
  --with-demo-data
```

如果 Docker Engine 与 Compose v2 已经就绪：

```bash
bash scripts/install.sh --skip-docker-install
```

Docker 官方仓库安装遇到发行版冲突包时，脚本会如实失败，不会自动删除现有容器运行时。请先按相应 Docker 官方文档处理冲突，再重新运行。

## macOS

```bash
bash scripts/install.sh
```

Docker 不存在时脚本使用已经安装的 Homebrew 执行 `brew install --cask docker`。脚本不会通过远程管道静默安装 Homebrew；没有 Homebrew 时请从 [brew.sh](https://brew.sh/) 安装，或自行安装 Docker Desktop。Docker Desktop 首次启动必须由用户完成可见的许可确认。

## 安装流程与幂等性

安装器依次执行：

1. 检查或安装 Docker 与 Compose v2；
2. 若 `.env` 不存在，从 `.env.example` 创建，并为 PostgreSQL、会话签名和通知加密生成随机值；
3. 若 `.env` 已存在，完整保留且不会被覆盖，不自动轮换可能已绑定数据卷的密码；
4. 校验 Compose 配置并构建、启动全部七个服务；
5. 等待 `/health/ready` 返回成功；API 启动过程自动执行 Alembic 迁移；
6. 创建首个管理员，写入不含密码且被 Git 忽略的 `.sio/install-state*`；
7. 幂等初始化平台目录、完整 7.9 规则、默认 Prompt/工作流、停用的 RSS 示例与停用的自动化示例；
8. 仅在显式参数存在时创建带 `source_kind=mock` 标识的 Demo 数据；
9. 确认 PostgreSQL、Redis、API、Worker、Beat、Web、Caddy 七个服务均在运行，并验证统一管理入口 `/login`。

重复运行不会修改已有 `.env`，也不会根据同一邮箱静默重置管理员密码。若数据库和管理员早于安装器状态文件存在，请使用 `-SkipBootstrap` 或 `--skip-bootstrap`，否则初始化会明确失败。

如果手动执行 `docker compose down -v` 删除了数据库卷，也应删除本地 `.sio/install-state*` 后重新运行安装器，否则安装器会按状态文件保留一个实际上已被删除的管理员。

## 安装完成后的入口

- 管理后台：<http://localhost:8080>
- API 文档：<http://127.0.0.1:8000/docs>
- 就绪检查：<http://127.0.0.1:8000/health/ready>

安装器面向单机本地部署，默认使用 HTTP 和开发环境 Cookie 设置，不等同于公网生产加固。公网部署前必须按 [DEPLOYMENT.md](DEPLOYMENT.md) 配置 TLS、安全 Cookie、备份、独立密钥、网络 ACL 与凭证管理。

## 常用参数

| Windows | Linux/macOS | 作用 |
| --- | --- | --- |
| `-AdminEmail` | `--admin-email` | 首个管理员邮箱 |
| `-AdminPassword` | `--admin-password` | 显式密码；省略时生成随机值 |
| `-WorkspaceName` | `--workspace-name` | 首个工作区名称 |
| `-WithDemoData` | `--with-demo-data` | 显式加入 Mock/Demo 监控数据 |
| `-SkipDockerInstall` | `--skip-docker-install` | 不安装 Docker，只验证现有运行时 |
| `-SkipBootstrap` | `--skip-bootstrap` | 保留既有管理员 |
| `-WaitSeconds` | `--wait-seconds` | 等待 Docker/API 就绪的秒数 |

非交互环境还可使用 `SIO_INSTALL_ADMIN_EMAIL`、`SIO_INSTALL_ADMIN_PASSWORD`、`SIO_INSTALL_WORKSPACE_NAME` 和 `SIO_INSTALL_WAIT_SECONDS`。CI 中的明文变量应来自 Secret 管理，不应写入仓库。

## 排错与停止

查看服务状态与日志：

```bash
docker compose ps
docker compose logs --tail=100 api worker beat
```

停止并保留 PostgreSQL/Redis 数据卷：

```bash
docker compose down
```

`docker compose down -v` 会永久删除本项目数据库和 Redis 数据卷，只应在确认不需要恢复任何数据时手动执行。更多问题见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。
