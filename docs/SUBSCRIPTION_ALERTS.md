# 订阅告警

订阅告警把账号、作品和热点事件的观测事实转换为可审计的通知投递。订阅规则、匹配事件和通知投递都按工作区隔离，并通过 `event_key` 与通知幂等键避免同一快照重复入队。

## 支持的触发器

- `new_content`：作品或账号快照首次出现时命中。
- `keyword_match`：标题、正文、描述或热点标题包含任一关键词时命中。
- `metric_spike`：当前指标达到绝对阈值，或相对上一快照增加指定值/倍率时命中。

规则可限定平台或账号，必须至少绑定一个已存在的启用通知渠道。命中后创建 `NotificationDelivery`，由既有通知 Worker 按 Provider 发送；没有可用渠道时事件保留为 `failed`，不会伪造发送成功。

## 后台入口与 API

后台入口为「设置 → 订阅告警」。API 使用当前工作区请求头：

- `GET/POST /api/v1/subscriptions`
- `GET/PATCH/DELETE /api/v1/subscriptions/{subscription_id}`
- `GET /api/v1/subscription-events`
- `POST /api/v1/subscriptions/evaluate`（运维重放与契约测试）

`POST /subscriptions/evaluate` 的 `source_kind` 只能是 `live` 或 `imported`，`event_key` 应来自真实快照或热点事件标识。后台扫描器每 30 秒扫描近期作品、账号快照和热点事件，使用同一服务评估规则。

## 运维边界

订阅评估只处理有限字段，并把来源标记、命中详情和投递 ID 写入事件审计。Provider 的真实发送仍取决于通知渠道配置与外部凭证；本地未配置凭证时应使用显式 Mock Provider 或仅做本地配置检查。冷却时间由规则的 `cooldown_seconds` 控制，冷却期间事件记录为 `suppressed`。

迁移为 `20260815_0002_subscription_alerts.py`。生产发布后先执行 `alembic upgrade head`，再检查订阅事件和通知投递队列；不要删除数据库卷来“修复”迁移。
