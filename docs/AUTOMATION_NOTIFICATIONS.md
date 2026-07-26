# 自动化规则与通知指南

## 已实现范围

Prompt 08 将自动化定义、条件求值、动作执行和通知发送拆为独立边界。规则使用结构化 JSON DSL，执行历史与运行时状态落库；通知渠道凭证经 Fernet 加密后保存，API 只返回脱敏摘要。

已实现条件组：`AND`、`OR`、`NOT`。已实现叶子操作符：`eq`、`ne`、`gt`、`gte`、`lt`、`lte`、`in`、`not_in`、`contains`、`not_contains`、`regex`、`changed`、`increased_by`、`increased_percent`、`consecutive_matches`。

条件求值采用三值逻辑：字段缺失或类型不兼容返回 `unknown`，最终按不匹配处理，同时在 `condition_result` 中保留原因。规则树限制为最多 100 个节点、8 层；字段按实体类型白名单校验；高风险正则构造被拒绝。

已实现动作：通知/通用 Webhook、创建选题、调用内容生成工作流、保存作品和外部 API 通知通道。动作依次执行并独立记录结果；某个生成动作失败时，后续通知仍会创建，并携带安全的失败摘要。

## 触发和防风暴

- Celery Beat 每 30 秒扫描最近账号快照、作品快照和热点事件，快照 ID 或事件更新时间形成事件幂等键。
- 同一规则和事件键只生成一次 `AutomationEvaluation`。
- `deduplication_window` 按规则、实体和时间桶去重。
- `cooldown_seconds` 按规则和实体保存冷却截止时间。
- `consecutive_matches` 使用持久化连续计数；Worker 重启不会清空状态。
- `source_kind=mock` 默认被生产触发链路阻断。只有显式测试模式或规则 `schedule.allow_mock=true` 才可求值和执行。
- 通知先落库为 `queued`，每 5 秒由投递调度任务分发；失败记录重试属性和安全错误，最多按后端配置尝试。

## 通知 Provider

统一接口包含 `validate_config`、`send`、`test` 和 `health_check`。首期实现：

| Provider key | 必要配置 | 说明 |
| --- | --- | --- |
| `email` | `host`、`from_email`、`to_emails` | 支持 TLS 或 SSL、可选 SMTP 认证 |
| `generic_webhook` | `url` | 可选请求头和 HMAC-SHA256 签名 |
| `telegram` | `bot_token`、`chat_id` | Telegram Bot API |
| `discord` | `webhook_url` | Discord Webhook |
| `feishu` | `webhook_url` | 可选签名密钥 |
| `dingtalk` | `webhook_url` | 可选时间戳签名密钥 |
| `wecom` | `webhook_url` | 企业微信群机器人 Webhook |
| `mock_notification` | 无 | 仅测试，回执显式标记 Mock |

Webhook URL 必须是公开 HTTP(S) 地址；配置时拒绝本机和直接私网地址，发送前再次解析 DNS 并拒绝非公网地址。HTTP 调用不跟随重定向，并具有超时、有限重试、限流和错误分类。

## 配置和初始化

生产环境必须设置独立的通知加密密钥：

```dotenv
SIO_NOTIFICATION_ENCRYPTION_KEY=replace-with-a-unique-secret-of-at-least-32-characters
SIO_NOTIFICATION_REQUEST_TIMEOUT_SECONDS=10
SIO_NOTIFICATION_REQUEST_MAX_ATTEMPTS=3
```

开发和测试环境未设置独立密钥时会从 `SIO_SECRET_KEY` 派生；生产环境禁止该回退。动作配置不能保存密码、Token、Secret 或 API Key，必须引用加密的通知渠道。

创建三个默认停用的示例规则：

```powershell
make seed-automations
```

示例在绑定实际渠道并由用户检查后才能启用，不会自动发送任何通知。

## API

- `GET/POST /api/v1/automations`
- `GET/PATCH/DELETE /api/v1/automations/{id}`
- `POST /api/v1/automations/{id}/actions`
- `DELETE /api/v1/automations/{id}/actions/{action_id}`
- `POST /api/v1/automations/validate`
- `POST /api/v1/automations/evaluate`
- `GET /api/v1/automation-evaluations`
- `GET /api/v1/notification-providers`
- `GET/POST /api/v1/notification-channels`
- `PATCH/DELETE /api/v1/notification-channels/{id}`
- `POST /api/v1/notification-channels/{id}/test`
- `GET /api/v1/notification-deliveries`

写操作需要有效会话、CSRF Token 和工作区角色。渠道响应永远不包含 `config_encrypted` 或明文配置。

## 真实数据和验证边界

自动化测试只发送到 `mock_notification`，不会联系外部渠道。Email、Webhook、Telegram、Discord、飞书、钉钉和企业微信的代码路径与配置契约已实现，但本机没有这些渠道的真实凭证，因此未执行真实发送验收，不能视为已验证外部投递成功。

首期扫描为 30 秒级近实时，不是消息总线级实时。投递使用数据库队列扫描；完整 Outbox 消费、每次网络尝试独立表、模板版本管理和分布式调度优化仍属后续扩展。
