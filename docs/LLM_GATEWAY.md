# LLM Gateway 集成指南

本文档说明如何在 Sports Intelligence OS 中启用和配置本地 LLM 网关服务。

## New API 网关

[New API](https://github.com/calcium-ion/new-api) 是一个统一的 OpenAI 兼容网关，支持 30+ 官方 LLM 提供商（OpenAI、Anthropic、Google、DeepSeek、Moonshot、智谱等）。通过一个入口即可管理多个上游 API Key，并支持负载均衡、额度控制和用量统计。

### 启用

```bash
docker compose --profile llm up -d
```

网关管理界面：http://localhost:3306

### 配置步骤

1. 启动后访问 http://localhost:3306，使用 root token 登录（默认为 `sio-local-gateway-token`，可通过 `SIO_LLM_GATEWAY_ROOT_TOKEN` 环境变量修改）。
2. 在「渠道」页面添加你的 LLM 提供商 API Key（如 OpenAI、DeepSeek 等）。
3. 在「令牌」页面创建或复制一个 API 令牌。

### 在 Sports Intelligence OS 中使用

在管理后台「设置 → LLM Provider 配置」中：

| 字段 | 值 |
|------|-----|
| 模型提供商 | New API 网关（本地） |
| API Base URL | `http://llm-gateway:3000/v1` |
| API Key | 网关中创建的令牌（或 root token） |
| 默认模型 | 网关中已配置渠道支持的任意模型，如 `gpt-4o-mini` |

> 在 Docker 网络内使用 `http://llm-gateway:3000/v1`；若从宿主机直接调用则使用 `http://localhost:3306/v1`。

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SIO_LLM_GATEWAY_SESSION_SECRET` | 网关会话签名密钥 | `sio-llm-gateway-local-session` |
| `SIO_LLM_GATEWAY_ROOT_TOKEN` | 网关管理员 root token | `sio-local-gateway-token` |
| `SIO_LLM_INTERNAL_HOSTS_ALLOWLIST` | 允许绕过 SSRF 检查的内部主机列表 | `["llm-gateway","llm-experimental"]` |

生产环境务必修改上述默认值。

---

## Chat2API 实验服务

[gpt4free](https://github.com/xtekky/gpt4free) 是一个实验性的 Web-to-API 转换器，通过逆向工程公开 Web 接口提供免费模型访问。

### 启用

```bash
docker compose --profile llm-experimental up -d
```

服务地址：http://localhost:8020

### 在 Sports Intelligence OS 中使用

| 字段 | 值 |
|------|-----|
| 模型提供商 | Chat2API 实验（本地） |
| API Base URL | `http://llm-experimental:8000/v1` |
| API Key | 留空或任意值 |
| 默认模型 | `gpt-4o` |

### 风险警告

- **不稳定**：依赖第三方 Web 接口，随时可能失效。
- **合规风险**：可能违反相关平台的服务条款（ToS）。
- **无 SLA**：不保证响应质量、延迟或可用性。
- **仅限开发/实验**：禁止用于生产环境或面向用户的内容生成。

---

## 提供商接入方式对照

| 提供商 | 官方 API | 推荐接入方式 | 需要 Chat2API |
|--------|----------|--------------|---------------|
| OpenAI | 是 | New API 网关 / 直连 | 否 |
| Anthropic (Claude) | 是 | New API 网关 / 直连 | 否 |
| Google Gemini | 是 | New API 网关 / 直连 | 否 |
| DeepSeek | 是 | New API 网关 / 直连 | 否 |
| Moonshot (Kimi) | 是 | New API 网关 / 直连 | 否 |
| 智谱 AI (GLM) | 是 | New API 网关 / 直连 | 否 |
| OpenRouter | 是 | 直连 | 否 |
| Ollama（本地） | 是 | 直连 | 否 |
| 其他 OpenAI 兼容接口 | 视情况 | New API 网关 / 直连 | 否 |

所有主流提供商均提供官方 API，建议优先使用官方渠道。Chat2API 仅作为技术实验保留，不推荐用于任何正式场景。

---

## SSRF 安全说明

系统对 LLM Base URL 执行 SSRF 防护检查（禁止解析到内网/回环地址）。Docker 内部服务名（如 `llm-gateway`、`llm-experimental`）通过 `SIO_LLM_INTERNAL_HOSTS_ALLOWLIST` 配置为白名单，跳过 DNS 解析检查。该白名单仅影响 LLM 请求路径，不影响新闻聚合等其他模块的 SSRF 策略。
