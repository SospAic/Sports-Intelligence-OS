# 通知 Provider 扩展指南

## 契约

实现配置校验、发送、测试和健康检查。输入统一为标题、正文、可选链接、结构化数据和幂等键；Provider 返回外部消息 ID 与安全元数据。

首期实现 Email、Generic Webhook、Telegram、Discord、飞书、钉钉和企业微信，另有显式 Mock Provider。

## 凭证

渠道配置在数据库中使用 Fernet 加密，API 只返回脱敏摘要。生产必须设置独立 `SIO_NOTIFICATION_ENCRYPTION_KEY`。不要把 Bot Token、Webhook Secret、SMTP 密码放进 AutomationAction。

## 出站安全与可靠性

- Webhook 配置与发送前都执行地址校验；发送前解析全部地址并拒绝非公网目标，不跟随重定向。
- 设定超时、有限重试和退避；失败记录 `retryable`，不会无限重试。
- `NotificationDelivery.idempotency_key` 防止同一动作重复投递。
- 原子状态认领防止多个 Worker 同时发送；超过 `SIO_TASK_STALE_AFTER_SECONDS` 的 `sending` 投递会释放为可审计失败并进入有限重试。
- AI 生成失败不阻断后续原始提醒。

## 新 Provider 流程

新增实现、描述字段、注册表项、共享类型和动态前端表单标签；补齐请求映射、签名、脱敏、失败分类和 Mock HTTP 测试。前端不得直接调用渠道 API。
