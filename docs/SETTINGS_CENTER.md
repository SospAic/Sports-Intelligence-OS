# 设置中心与配置边界

更新日期：2026-07-26

## 1. 配置分层

设置页 `/settings` 将参数分为两类，避免运行中的应用改写自身基础设施后失联：

- **部署级配置**：应用、PostgreSQL、Redis/Celery、同步任务、平台凭证、会话与安全参数。API 只返回脱敏当前值和环境变量名，页面可调整并复制 `.env` 草稿；实际值由运维写入 `.env`、Docker Secret 或平台 Secret Manager，重启 API、Worker、Beat 后生效。
- **工作区级配置**：OpenAI 兼容 LLM 和通知渠道。Owner/Admin 可在页面保存；敏感值在后端加密，读取接口只返回配置状态与脱敏摘要，新生成/通知任务直接使用数据库配置。

数据库和 Redis 的含凭证 URL 不会返回，也不会进入页面生成的草稿。它们属于部署诊断，不再作为设置页 Tab；平台凭证统一在“平台管理”维护，避免出现重复入口。Compose 内部主机固定为 `postgres` / `redis`；不要把宿主机 `127.0.0.1` URL直接复制到容器。

## 2. 部署级细项

`GET /api/v1/settings/runtime` 仍为运维/健康诊断接口，但不再由设置页渲染为独立 Tab：

| 分组 | 主要参数 |
| --- | --- |
| 应用与网络 | 应用名/版本、日志级别、API Host/Port、CORS Origin JSON、Cookie 名称 |
| PostgreSQL | 脱敏连接拓扑、pool size、max overflow、获取连接超时、连接回收、SQL 命令超时 |
| Redis/Celery | 脱敏连接拓扑、连接/读写超时、最大连接数、健康检查周期、超时重试 |
| 同步与任务 | 平台请求超时/尝试次数、同步整体墙钟预算、任务重试、失联租约、分页上限、通知全局超时/尝试次数 |
| 会话与安全 | Secure Cookie、会话 TTL、登录限流窗口/账号/IP 上限、记录保留期、密码长度、独立密钥状态 |

Compose 会把上述可变参数显式传入 API、Worker 和 Beat。`SIO_DATABASE_URL` 与 `SIO_REDIS_URL` 在默认 Compose 中使用容器内部连接地址；生产可通过覆盖文件或编排平台替换。

## 3. LLM API

工作区设置支持：Base URL、API Key、Organization、Project、自定义请求头、默认模型、Temperature、Top P、最大 Token、单次超时、最大尝试次数、输入/输出每百万 Token 成本和启停。

- 保存到 `llm_provider_settings`；连接配置为 Fernet 密文，API Key 和自定义头不明文回传。
- 空白 API Key 保留已有值；显式勾选“清除”才删除。
- 保存后，手动生成、Celery Worker 生成和自动化 `create_generation` 均解析工作区配置。
- 模型提供商下拉先提供供应商目录；保存配置后，`GET /api/v1/settings/llm/models` 会真实请求当前 Base URL 的 `/models` 并将可用模型填入下拉框。该请求会再次执行 DNS/IP SSRF 防护，不跟随重定向，不伪造成功。
- 首期数据库配置仅提供一个 OpenAI 兼容连接；Mock LLM 仍仅用于显式测试输出。Ollama 私网地址、厂商专有协议和流式输出仍不属于本次增量范围。

## 4. 通知 Provider

设置页与独立 `/notification-channels` 页面复用同一动态字段契约：

| Provider | 细项 |
| --- | --- |
| Email | SMTP Host/Port、用户名/密码、发件人、多个收件人、Reply-To、主题前缀、STARTTLS/SSL、超时 |
| Generic Webhook | URL、附加 Header JSON、HMAC Secret、超时、最大尝试次数 |
| Telegram | Bot Token、Chat ID、Parse Mode、链接预览、静默、Thread ID、超时/重试 |
| Discord | Webhook URL、机器人名称、头像 URL、TTS、超时/重试 |
| 飞书 | Webhook URL、签名 Secret、@所有人、超时/重试 |
| 钉钉 | Webhook URL、加签 Secret、@手机号、@所有人、超时/重试 |
| 企业微信 | Webhook URL、@用户 ID、@手机号、超时/重试 |

字段类型、必填、范围、默认值和帮助文本由 Provider 后端声明，前端不硬编码平台分支。编辑时空白敏感字段保留原值；Webhook、Token、密码和 Header 值只返回掩码。真实测试发送前有二次确认，投递失败保留真实状态与安全错误摘要。

## 5. 权限、审计与安全

- 已登录成员可读取脱敏配置状态；只有 Owner/Admin 可保存 LLM、创建/编辑/测试通知渠道。
- LLM 配置创建、更新和测试写入 `audit_entries`；通知变更沿用通知域审计。
- 登录限流只保存 HMAC 哈希后的身份和客户端地址、时间及成功状态，不保存提交邮箱或原始 IP；过期尝试和失效 Session 由每小时维护任务清理。
- 外部 HTTP Provider 在保存时校验 URL 结构，并在每次真实请求前重新解析全部地址，拒绝私网、环回、链路本地和重定向。
- 页面不会写入宿主机 `.env`，也不会把 API Key 放入浏览器缓存、Prompt 预览或日志。

## 6. 当前边界

数据库/Redis 在线改密、连接切换和进程重启属于部署平台权限，不能由普通 Web 请求完成。真实 YouTube、LLM 与通知验收仍需要用户提供有效凭证；未配置时系统报告真实错误或不可用状态，不会自动切换成 Mock。
