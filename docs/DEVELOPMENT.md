# 开发指南

## 本地依赖

- Python 3.12
- Node.js 24、pnpm 11.9
- PostgreSQL 17、Redis 7.4；单元测试使用本地 Docker PostgreSQL 隔离数据库

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
pnpm install --frozen-lockfile
Copy-Item .env.example .env
```

## 进程

API、Worker、Beat 和 Web 必须分进程运行。后端共享代码位于 `apps/api/app`；`apps/worker` 只提供 Celery 入口。前端只调用 `/api/v1`，不得直接请求第三方平台。

```powershell
Push-Location apps\api
..\..\.venv\Scripts\python.exe -m alembic upgrade head
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
Pop-Location
pnpm dev
```

## 质量门禁

```powershell
.\scripts\check.ps1
```

或分别运行 Ruff、Mypy、Pytest、TypeScript、ESLint、Vitest、Prettier 和 Next.js 构建。`pytest -m integration` 运行本地确定性多模块链路，不访问外部平台。

## 测试结构

- `apps/api/tests`：领域、API、Adapter/Provider 和 Mock 垂直链路。
- `apps/web/**/*.test.ts(x)`：查询契约、编辑器、登录、生成和通知交互。
- `tests`：仓库阶段、基础设施和真实性契约。

禁止删除失败测试来通过门禁。修复缺陷后应保留最小回归用例。

## 数据库与类型

- 模型变更必须增加 Alembic 迁移，并执行 upgrade、downgrade、re-upgrade 与 `alembic check`。
- 快照表 append-only，禁止更新历史行。
- 时间写入 UTC；从外部 Provider 读取的无时区时间必须在边界归一化。
- 高频公共字段结构化，平台低频字段进入 `metadata`。

## 新接入边界

平台、新闻、LLM 和通知分别遵循对应 Provider 指南。业务 Service 不得添加平台名称分支；密钥不得进入前端、日志、Fixture 或提交记录。
