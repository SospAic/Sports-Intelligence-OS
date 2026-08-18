# LLM Provider 扩展指南

## 契约

实现配置校验、`generate`、`stream`、成本估算和健康检查。Provider 接收已冻结的消息、参数、响应 Schema、超时、幂等键和元数据；不得自行选择规则或 Prompt 版本。

## 密钥与日志

API Key 只从后端环境或工作区加密配置读取。`llm_provider_settings` 保存密文、独立脱敏摘要、默认模型/参数、费率和健康状态；只有 Owner/Admin 可写。Provider 描述、Prompt 预览、异常和结构化日志不得回显 Key、Authorization 或完整敏感请求头。

工作区配置会覆盖环境中的默认连接，并用于 API、Worker 和自动化生成。配置同时保存稳定的 `provider_id`（如 `openai`、`ollama`、`new-api`）和可自定义的显示名称，不再把所有连接显示为“OpenAI 兼容接口”。支持 Base URL、Organization、Project、自定义 Header、模型、Temperature、Top P、最大 Token、超时、重试与输入/输出费率。粘贴 `/models` 或 `/chat/completions` 后缀时会在服务端规范化为 API 根地址；空白 Key 保留旧值，显式清除才删除。连接测试调用真实 `/models` 并执行 DNS/IP 复核，返回模型数量并校验默认模型是否出现在列表中；这是非计费的配置/模型可用性检查，不等同于一次真实生成。

Docker Desktop 或透明代理可能把公网 API 域名解析为合成的非公网地址。内置公网 LLM Provider（包括 OpenAI、Gemini、DeepSeek、Qwen、智谱、Moonshot、OpenRouter 等）使用严格的官方域名边界兼容检查，不会因这类合成 DNS 被误判；未知的自定义 Endpoint 仍必须解析到全球可路由地址。Ollama 的 Docker 配置应使用 `http://host.docker.internal:11434/v1`，并保留在 `SIO_LLM_INTERNAL_HOSTS_ALLOWLIST` 中；`localhost` 指向 API 容器本身，不是宿主机上的 Ollama。

测试未保存表单时只验证当前输入，不落库；保存后不带请求体测试才会更新工作区健康状态和审计记录。状态面板会明确显示 `workspace`、`environment` 或 `none` 生效范围及实际生效任务。Ollama、Chat2API、New API 支持无 Key 的本地/自托管模式，但仍须成功返回模型列表；未实现原生 Anthropic/Bedrock 协议时不会把它们伪装成 OpenAI 兼容 Provider。

## 输出与真实性

- 原始 Provider 响应与最终输出分别持久化。
- Token、耗时、模型、参数和估算成本保留在 GenerationRun。
- Mock Provider 输出必须带 `MOCK TEST OUTPUT` 和 `source_kind=mock`。
- Provider 不能把模型陈述当作联网核实；事实来源和 `verification_status` 由工作流控制。

## Prompt 注入边界

用户/新闻/作品内容作为数据变量传入，不得拼接为系统权限指令。渲染器拒绝未声明变量，预览递归脱敏；输出仍需 QA 和事实审查，不能将模型输出直接当作可信命令执行。

7.9 工作流支持在输入中声明 `answer_word` 或 `protected_answer_words`。确定性 QA 默认要求答案词首次出现位于文案后 55%，提前出现或最终缺失都会触发有限重写；没有明确答案词时不会凭空猜测一个词并伪装成已检查。

## 测试

覆盖超时、有限重试、无 Key、严格变量、脱敏、结构化响应失败、成本估算、最大自动重写次数和幂等运行。真实可计费测试默认关闭。
