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
- Celery 任务有 1,800 秒软限制和 1,860 秒硬限制；默认 2,100 秒租约只用于确认 Worker 已失联后释放锁或失败状态，不能设置得短于正常最大任务时间。

## 备份

至少备份 PostgreSQL；Redis 是队列与短期状态，不应是唯一业务事实来源。备份必须包含通知配置加密密钥，否则加密渠道配置无法恢复。恢复后先运行迁移与只读健康检查，再开放写流量。

## 扩容边界

可增加 Worker 副本，但 Beat 保持单实例；账号锁、通知幂等键和冷却状态位于数据库。首期没有消息总线级事件流、死信队列或跨区域复制，达到相关容量前应先测量而不是直接引入重型组件。
