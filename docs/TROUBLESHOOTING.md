# 故障排查

## Compose 无法启动

先运行 `docker compose config`，再查看 `docker compose ps` 与 `docker compose logs --tail=200 <service>`。端口 5432、6379、3000、8000 或 8080 被占用时，修改本地端口映射，不要修改容器内部服务名。

## API 未就绪

- `/health/live` 失败：检查 API 启动和迁移日志。
- `/health/ready` degraded：分别检查 PostgreSQL 与 Redis 健康状态。
- 迁移错误：在 `apps/api` 工作目录执行 `alembic current`、`alembic upgrade head`，不要删除数据卷掩盖错误。

## 无法登录

确认已设置 bootstrap 邮箱/密码并运行 `make seed`。系统没有默认管理员密码；重复执行不会静默重置密码。浏览器必须通过同一入口访问，避免 Cookie 域和 CSRF 来源不一致。

## YouTube 同步失败

- `adapter_configuration_error`：未配置 `SIO_YOUTUBE_API_KEY`。
- `quota_exceeded`：等待配额恢复或调整同步频率。
- 无效/私有频道或删除作品会保留明确错误/状态，不会切换到 Mock。

## RSS 没有文章

确认来源已启用、URL 可公开访问且不是私网地址，检查同步记录。域名只要解析到环回、私网或链路本地地址就会被拒绝；新闻源 URL 不能携带明文 Token。缺少发布时间的文章仍可保存，但发布时间为空；默认示例源初始停用。

## 生成失败

先确认已导入并发布 7.9 规则、运行 `make seed-generation`。真实 Provider 需要后端 Base URL、API Key 和模型；Mock LLM 不需要 Key，但只产生测试输出。查看 GenerationRun 的失败步骤和安全错误。

## 通知失败

确认渠道已启用、配置健康、加密密钥没有变化。Webhook 私网地址会被拒绝。查看 `NotificationDelivery.attempts`、`error` 和 Provider 回执；AI 失败时原始通知仍应继续。

## Worker 或 Beat 不工作

检查 Redis、Worker 队列列表和 Beat 单实例。同步任务长期 queued 通常表示 Broker/Worker 不可用。系统默认以 2,100 秒为执行租约：失联同步锁会释放，失联通知会进入有限重试，陈旧排队生成会重投，陈旧运行生成会标记失败供人工重试；不会无限重试或静默删除失败记录。

## Redis 因 AOF 损坏反复重启

如果 `docker compose ps redis` 显示 `Restarting (1)`，且日志包含
`Bad file format reading the append only file`，先不要执行 `docker compose down -v`。
这通常表示 Redis 的多段 AOF 增量文件末尾存在异常截断；Redis 的 base RDB
仍可能可以正常加载。安全恢复顺序如下：

1. `docker compose stop redis`
2. 在 Redis named volume 内备份 `appendonlydir/appendonly.aof.manifest`、当前
   `*.base.rdb` 和当前 `*.incr.aof`，并记录 SHA-256。
3. 使用同版本镜像执行只针对当前增量文件的
   `redis-check-aof --fix`，确认它只截去损坏尾部后再输入 `y`。
4. `docker compose up -d redis`，确认 `docker compose ps redis` 为 healthy、
   `docker compose exec redis redis-cli ping` 返回 `PONG`，再检查
   `http://localhost:8000/health/ready` 的 `redis` 为 `ok`。

本项目 Redis 只承载 Celery Broker、缓存和短期状态；业务事实在 PostgreSQL。
修复前必须保留 AOF 备份，不能用删除 `redis_data` 卷的方式“恢复”。

## 清理

`docker compose down` 保留数据；`docker compose down -v` 会删除数据库和 Redis 卷，仅可在明确要销毁本地数据时使用并应先备份。
