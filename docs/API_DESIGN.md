# Sports Intelligence OS API 设计

文档状态：Prompt 01 接口基线  
协议：REST/JSON，OpenAPI 3.1  
基础路径：`/api/v1`

## 1. API 原则

- 浏览器和其他客户端只调用本系统 API；FastAPI 在服务端调用第三方 Provider。
- 路由只做认证、授权、校验和 HTTP 映射；业务逻辑位于应用用例。
- 长任务创建运行资源并返回 `202 Accepted`；不在请求中等待平台同步、新闻抓取或 LLM 工作流。
- 请求/响应 schema 独立于 ORM；OpenAPI 生成 TypeScript 类型/客户端。
- 工作区是 URL 中显式隔离边界：`/workspaces/{workspace_id}/...`。
- 版本化资源发布后不可更新；编辑通过创建新草稿/版本完成。

## 2. 传输约定

### 2.1 格式与时间

- JSON 使用 UTF-8；字段 `snake_case`，生成的 TS 客户端保留相同名称。
- ID 为 UUID 字符串；时间为 ISO 8601 UTC，例如 `2026-07-25T08:00:00Z`。
- 计数作为 JSON number，但前端类型对超出安全整数的值使用字符串/BigInt 转换策略；OpenAPI 明确 `int64`。
- 比率 0–1；金额返回 decimal 字符串 + currency，防止浮点误差。
- 可选但缺失的指标为 `null`，并通过 `metric_availability` 或 quality 解释；不填 0。

### 2.2 请求头

- `X-Request-Id`：可选客户端请求 ID；服务端始终返回。
- `Idempotency-Key`：创建运行、手动同步、测试通知等副作用 POST 必需。
- `If-Match`：更新可变配置时使用 ETag/row version 防覆盖。
- `X-CSRF-Token`：Cookie 会话下所有状态变更请求必需。

### 2.3 响应头

- `X-Request-Id` / `Traceparent`（采用 W3C trace context 时）。
- `ETag`：可变资源详情。
- `Location`：201 创建资源或 202 运行资源地址。
- Rate limit 头仅描述本系统限制，不冒充第三方配额。

## 3. 错误模型

采用 RFC 9457 Problem Details 风格：

```json
{
  "type": "https://sports-intelligence.local/problems/validation-error",
  "title": "请求参数无效",
  "status": 422,
  "code": "validation_error",
  "detail": "一个或多个字段无效",
  "instance": "/api/v1/workspaces/.../platform-accounts",
  "request_id": "uuid",
  "errors": [
    {"path": "body.locator", "code": "required", "message": "不能为空"}
  ]
}
```

稳定 `code` 供客户端分支；`detail` 可本地化。生产响应不包含堆栈、SQL、Token 或完整 Provider 响应。

常用状态：400 业务格式错误、401 未认证、403 无权限、404 资源不存在（也用于隐藏跨工作区资源）、409 状态/唯一冲突、412 ETag 失败、422 schema 校验、429 本系统限流、503 依赖暂不可用。

## 4. 分页、筛选与排序

列表默认游标分页：

```json
{
  "items": [],
  "page": {
    "next_cursor": "opaque-or-null",
    "has_more": false,
    "limit": 50
  }
}
```

- `limit` 默认 50，最大 200。
- Cursor 由排序字段、ID 和过滤器哈希签名，客户端不得解析。
- `sort=-published_at,title`；每个端点有排序 allowlist。
- 简单过滤使用查询参数；复杂规则使用专门的结构化 body，不开放任意 SQL/字段路径。
- 导出是异步运行，不绕过权限和行数限制。

## 5. 认证与用户

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/auth/login` | 邮箱密码登录，建立 HttpOnly Session |
| POST | `/auth/logout` | 撤销当前 Session |
| POST | `/auth/refresh` | 轮换会话（若采用短会话分段） |
| GET | `/auth/csrf` | 获取绑定会话的 CSRF token |
| GET | `/me` | 当前用户、工作区成员关系和权限摘要 |
| PATCH | `/me/preferences` | locale、timezone 等个人偏好 |

首期不公开自助注册端点，初始管理员通过受控 bootstrap 命令创建；是否开放注册由部署配置决定。

## 6. 工作区、成员与连接

| 方法 | 路径 | 权限/说明 |
| --- | --- | --- |
| GET | `/workspaces` | 当前用户可见工作区 |
| GET | `/workspaces/{wid}` | `workspace:read` |
| PATCH | `/workspaces/{wid}` | `workspace:manage` + If-Match |
| GET | `/workspaces/{wid}/members` | `members:read` |
| POST | `/workspaces/{wid}/members` | `members:manage`；首期可只添加已有用户 |
| PATCH | `/workspaces/{wid}/members/{uid}` | 角色/状态，保护最后 Owner |
| GET | `/workspaces/{wid}/connections` | `integrations:read`；秘密不回显 |
| POST | `/workspaces/{wid}/connections` | `integrations:manage` |
| PATCH | `/workspaces/{wid}/connections/{id}` | If-Match；秘密使用 replace 语义 |
| POST | `/workspaces/{wid}/connections/{id}/verify` | 202，返回 Operation |
| DELETE | `/workspaces/{wid}/connections/{id}` | 软删除/依赖检查，写审计 |
| GET | `/providers` | 可用 Provider 描述和能力，不含秘密 |

当前兼容入口还提供账号级范围授权：`GET/POST /api/v1/workspace-account-grants` 与 `DELETE /api/v1/workspace-account-grants/{grant_id}`，仅 owner/admin 可管理并要求 CSRF。详见 [`WORKSPACE_ACCOUNT_ACCESS.md`](WORKSPACE_ACCOUNT_ACCESS.md)。

Connection 返回 `secret_configured`、验证状态、能力和掩码，不返回密文或 secret ref。

## 7. 平台账号、作品与同步

### 7.1 Prompt 03 已实现兼容入口

Prompt 03 按用户指定路径实现 `/api/v1/platforms`、`/accounts`、`/contents` 及其详情、快照、指标和 CSV 导出。工作区由唯一活动成员关系或 `X-Workspace-Id` 解析，避免前端提交任意工作区 ID。下述显式 `/workspaces/{wid}` 路径仍是后续 API 演进基线；在引入前保持当前入口兼容。

Prompt 04 已将 `POST /accounts/{id}/sync` 替换为真实 202 SyncRun：请求先持久化、活动任务按账号锁幂等复用，再投递 Celery；Broker 投递失败会转为可见的 503 和终态错误记录。`GET /accounts/{id}/sync-runs` 提供运行历史。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/workspaces/{wid}/platform-accounts` | 列表 / 通过 connection + locator 添加 |
| GET/PATCH | `/workspaces/{wid}/platform-accounts/{id}` | 详情 / 本地显示和计划设置 |
| DELETE | `/workspaces/{wid}/platform-accounts/{id}` | 停用并保留历史，需权限 |
| POST | `/workspaces/{wid}/platform-accounts/{id}/sync-runs` | 202 手动同步，Idempotency-Key |
| GET | `/workspaces/{wid}/platform-accounts/{id}/snapshots` | 时间范围、粒度、指标筛选 |
| GET | `/workspaces/{wid}/platform-accounts/{id}/media` | 作品列表 |
| GET | `/workspaces/{wid}/media/{media_id}` | 作品详情 |
| GET | `/workspaces/{wid}/media/{media_id}/snapshots` | 历史快照/派生指标 |
| GET/PATCH | `/workspaces/{wid}/platform-accounts/{id}/sync-schedule` | 定时同步计划 |
| GET | `/workspaces/{wid}/sync-runs/{run_id}` | 状态、计数、安全错误摘要 |

列表项和详情都返回：`source_kind`、Provider、最近抓取时间、数据新鲜度和 Mock 标签。响应中的能力说明区分 reported/derived/unavailable。

## 8. 新闻与事件

> Prompt 05 已实现 `/api/v1/news/sources`、`articles`、`events`、同步日志、手动合并/拆分/收藏及版本化 `/scoring-config`。当前路径使用认证上下文解析工作区；下表显式工作区路径继续作为后续演进基线。详细参数与真实性边界见 `docs/NEWS_AGGREGATION.md`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/workspaces/{wid}/news-sources` | RSS/Provider 源列表与创建 |
| GET/PATCH/DELETE | `/workspaces/{wid}/news-sources/{id}` | 详情、配置、停用 |
| POST | `/workspaces/{wid}/news-sources/{id}/fetch-runs` | 202 手动抓取 |
| GET | `/workspaces/{wid}/news-articles` | 时间、来源、运动、人物/队伍搜索 |
| GET | `/workspaces/{wid}/news-articles/{id}` | 当前修订、来源、评分、事件关联 |
| GET | `/workspaces/{wid}/news-articles/{id}/revisions` | 内容更新历史 |
| GET | `/workspaces/{wid}/news-events` | 事件列表、趋势和筛选 |
| GET/PATCH | `/workspaces/{wid}/news-events/{id}` | 详情；人工确认字段需编辑权限 |
| POST | `/workspaces/{wid}/news-events/{id}/articles` | 人工关联文章 |
| DELETE | `/workspaces/{wid}/news-events/{id}/articles/{article_id}` | 解除人工/自动关联并记录原因 |

原始正文的返回受来源许可和权限控制；默认 API 返回安全摘录与原链接。

## 9. Editorial Rules

路径使用 `editorial-rule-sets`，避免与 Automation Rules 混淆。

> Prompt 06 已提供兼容首期管理界面的 `/api/v1/rules` 路径，覆盖集合、版本、树、筛选、单条/批量编辑、验证、发布、回滚、比较以及 TXT/JSON 导入导出。工作区由认证上下文和 `X-Workspace-Id` 解析；所有写操作使用 CSRF。下表显式工作区路径仍是后续 API 演进基线。
>
> Prompt 07 已实现 `/api/v1/prompts`、`/api/v1/workflows`、`/api/v1/llm/providers` 与 `/api/v1/generations` 资源族：Prompt 草稿/发布/回滚、十步工作流读取、后端 Provider 状态、安全预览、幂等创建、步骤进度、失败重试、手动重写、采用及 JSON/TXT 导出。API 不返回 LLM 明文密钥。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/workspaces/{wid}/editorial-rule-sets` | 集合列表/创建 |
| GET | `/workspaces/{wid}/editorial-rule-sets/{id}` | 当前发布和草稿摘要 |
| POST | `/workspaces/{wid}/editorial-rule-sets/{id}/versions` | 从空白/旧版本创建草稿 |
| GET/PATCH | `/workspaces/{wid}/editorial-rule-sets/{id}/versions/{vid}` | 草稿详情/编辑；发布版只读 |
| GET | `/.../versions/{vid}/tree` | 章节/规则树 |
| POST/PATCH/DELETE | `/.../versions/{vid}/nodes[...]` | 草稿结构化节点操作 |
| POST | `/.../versions/{vid}/validate` | 校验依赖、冲突、来源追踪 |
| POST | `/.../versions/{vid}/publish` | 发布并写审计 |
| POST | `/.../versions/{vid}/rollback` | 重新指向旧发布版本，创建审计记录 |
| GET | `/.../versions/{a}/diff/{b}` | 版本差异 |
| POST | `/workspaces/{wid}/editorial-rule-imports` | 202 上传/导入原文 |
| GET | `/workspaces/{wid}/source-artifacts/{id}` | 元数据；下载需额外权限 |

## 10. Prompt 与 Workflow 定义

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/workspaces/{wid}/prompt-templates` | 模板列表/创建 |
| POST | `/workspaces/{wid}/prompt-templates/{id}/versions` | 创建草稿版本 |
| GET/PATCH | `/.../versions/{vid}` | 查看/编辑草稿正文和 schema |
| POST | `/.../versions/{vid}/validate` | 变量、模板、输出 schema 校验 |
| POST | `/.../versions/{vid}/test-runs` | 202，使用测试输入/Provider |
| POST | `/.../versions/{vid}/publish` | 发布 |
| GET | `/.../versions/{a}/diff/{b}` | 版本对比 |
| GET/POST | `/workspaces/{wid}/workflows` | 工作流定义 |
| GET/POST/PATCH | `/workspaces/{wid}/workflows/{id}/versions[...]` | 版本、草稿编辑和发布 |

Prompt 正文只向有 `prompts:manage` 的成员开放；运行使用权限可与查看正文分离。

## 11. Generation Runs

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/workspaces/{wid}/generation-runs` | 列表 / 创建，POST 返回 202 |
| GET | `/workspaces/{wid}/generation-runs/{id}` | 运行状态、固定版本和用量摘要 |
| POST | `/workspaces/{wid}/generation-runs/{id}/cancel` | 协作式取消 |
| POST | `/workspaces/{wid}/generation-runs/{id}/retry` | 从允许检查点创建 attempt/新 run |
| GET | `/workspaces/{wid}/generation-runs/{id}/steps` | 各步骤和 findings |
| GET | `/workspaces/{wid}/generation-runs/{id}/artifacts` | 按类型筛选产物 |
| GET | `/workspaces/{wid}/generation-runs/{id}/artifacts/{aid}` | 授权后读取内容 |
| POST | `/workspaces/{wid}/generation-runs/{id}/decision` | 评分、采用或拒绝 |

创建请求只引用发布版本或允许的草稿测试版本。服务端解析成具体 Version ID 并固定；不接受客户端直接提交任意 Prompt 文本冒充模板。

## 12. Automation Rules

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/workspaces/{wid}/automation-rules` | 规则列表/创建 |
| GET/PATCH | `/workspaces/{wid}/automation-rules/{id}` | 元数据、启停、优先级；If-Match |
| POST | `/workspaces/{wid}/automation-rules/{id}/versions` | 创建条件/动作草稿 |
| GET/PATCH | `/.../versions/{vid}` | AST 草稿；发布版只读 |
| POST | `/.../versions/{vid}/validate` | schema、类型、字段、动作引用 |
| POST | `/.../versions/{vid}/dry-runs` | 使用历史/测试事件，绝不执行副作用 |
| POST | `/.../versions/{vid}/publish` | 发布 |
| GET | `/workspaces/{wid}/rule-evaluations` | 命中、未命中、抑制和错误 |
| GET | `/workspaces/{wid}/rule-evaluations/{id}` | Explain tree 与动作状态 |
| GET | `/workspaces/{wid}/action-executions` | 动作运行列表 |

## 13. 通知

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/workspaces/{wid}/notification-channels` | 渠道列表/创建 |
| GET/PATCH/DELETE | `/workspaces/{wid}/notification-channels/{id}` | 配置与停用；秘密不回显 |
| POST | `/workspaces/{wid}/notification-channels/{id}/verify` | 202 验证配置 |
| POST | `/workspaces/{wid}/notification-channels/{id}/test-notifications` | 202 真实测试，显著标记 |
| GET | `/workspaces/{wid}/notifications` | 通知列表 |
| GET | `/workspaces/{wid}/notifications/{id}` | 内容摘要和投递状态 |
| GET | `/workspaces/{wid}/notifications/{id}/attempts` | 各次投递安全摘要 |
| POST | `/workspaces/{wid}/notifications/{id}/retry` | 仅对明确可重试/人工确认状态 |

## 14. 运营、审计与异步资源

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health/live` | 进程存活，不检查所有外部系统 |
| GET | `/health/ready` | 数据库/必要依赖就绪；内部或受控访问 |
| GET | `/workspaces/{wid}/operations/{id}` | 通用 202 Operation 状态 |
| GET | `/workspaces/{wid}/task-runs` | 后台任务状态 |
| GET | `/workspaces/{wid}/system-events` | 可筛选运营事件 |
| GET | `/workspaces/{wid}/audit-entries` | 高权限、只读、分页 |
| GET | `/workspaces/{wid}/events/stream` | 可选 SSE，发送资源状态变化而非秘密内容 |

### Operation 响应

```json
{
  "id": "uuid",
  "type": "platform_sync",
  "status": "queued",
  "resource": {"type": "sync_run", "id": "uuid"},
  "progress": {"current": 0, "total": null},
  "created_at": "2026-07-25T08:00:00Z",
  "links": {"self": "/api/v1/workspaces/.../operations/..."}
}
```

SSE 断开不影响任务；客户端始终可通过 GET 恢复状态。首期可只轮询，SSE 在 Prompt 09 根据 UX 需要实现。

## 15. 权限约定

每个端点声明细粒度 permission，例如 `accounts:read`、`accounts:manage`、`sync:run`、`news:manage`、`editorial_rules:publish`、`generation:run`、`automation:publish`、`notifications:manage`、`audit:read`。

服务端在应用用例入口再次断言工作区与权限，不能只依赖前端隐藏按钮。角色映射见 `docs/SECURITY.md`。

## 16. 批量与导出

- 批量输入有上限并逐项返回成功/失败；涉及长任务时创建 Batch Operation。
- 导出创建异步 `export_run`，按工作区权限和筛选条件生成有过期时间的下载。
- CSV 防公式注入；敏感字段默认排除；导出写审计。
- 不提供任意数据库查询或任意字段 JSON 导出。

## 17. API 演进与兼容

- URL 主版本仅在破坏性变更时提升；同版本新增可选字段保持兼容。
- OpenAPI 是客户端契约源；CI 检测破坏变更并生成 `packages/api-contract`。
- Event schema 与 REST API 独立版本化。
- 废弃字段先标 deprecated、记录使用、提供迁移窗口，再在新主版本移除。

## 18. 测试要求

- OpenAPI schema 快照与生成客户端类型检查。
- 每个端点的未认证、无权限、跨工作区、无效 ID、冲突和 ETag 测试。
- 游标与过滤器绑定、稳定排序、limit 上限。
- Idempotency-Key 重放相同请求返回同一资源；不同 body 冲突。
- 202 Operation 最终状态与实际 Context Run 一致。
- API 响应不泄露 secret、密文、内部堆栈或 Provider 原始敏感响应。
- Mock 来源在列表、详情、导出契约中始终可识别。

## 19. Prompt 08 落地说明

Prompt 08 已落地 `/automations`、`/automation-evaluations`、`/notification-providers`、`/notification-channels` 和 `/notification-deliveries` API。条件校验与执行分离；求值响应保留逐节点说明、抑制原因和动作结果。通知渠道的写入请求可包含凭证，但读取响应只包含 `config_masked`，永不返回密文或明文配置。所有写操作继续执行会话、工作区角色和 CSRF 校验。

完整路由、Provider 配置和真实发送边界见 [AUTOMATION_NOTIFICATIONS.md](AUTOMATION_NOTIFICATIONS.md)。

## 20. Prompt 09 落地说明

Prompt 09 新增 `/topics`、`/topics/batch`、`/operations/tasks`、`/operations/events` 和 `/operations/audits`。选题写操作使用工作区角色与 CSRF 保护；批量来源必须存在且属于当前工作区。运营端点只返回安全摘要，不返回通知密文、IP 哈希或 Provider 原始响应。管理后台继续通过同源 `/api/v1` 代理调用后端，前端不直连外部平台。

## 21. 设置中心增量

| 方法 | 路径 | 权限与语义 |
| --- | --- | --- |
| GET | `/settings/runtime` | 已登录工作区成员；返回脱敏部署参数描述和环境变量名，不写宿主机配置 |
| GET | `/settings/llm/openai-compatible` | 已登录工作区成员；只返回配置状态、脱敏摘要和默认参数 |
| PUT | `/settings/llm/openai-compatible` | Owner/Admin + CSRF；加密保存工作区连接与模型参数 |
| POST | `/settings/llm/openai-compatible/test` | Owner/Admin + CSRF；对已保存公网连接执行真实 `/models` 验证 |

`GET /llm/providers` 现在按工作区解析 Provider 来源、默认模型和默认参数。`GET /notification-providers` 返回类型化 `config_fields`，供设置页和通知页生成相同的动态表单。所有读取接口均排除密文和明文 Secret。
