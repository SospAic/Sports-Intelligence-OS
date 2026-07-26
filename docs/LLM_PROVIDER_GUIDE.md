# LLM Provider 扩展指南

## 契约

实现配置校验、`generate`、`stream`、成本估算和健康检查。Provider 接收已冻结的消息、参数、响应 Schema、超时、幂等键和元数据；不得自行选择规则或 Prompt 版本。

## 密钥与日志

API Key 只从后端环境或未来安全存储读取。Provider 描述、Prompt 预览、异常和结构化日志不得回显 Key、Authorization 或完整敏感请求头。

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
