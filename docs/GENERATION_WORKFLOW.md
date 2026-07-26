# Prompt 与内容生成工作流指南

文档状态：Prompt 07 已实现  
更新日期：2026-07-26

## 1. 已实现范围

- `PromptCollection` 与不可原地修改的 `PromptVersion`。
- `GenerationWorkflow`、`GenerationRun` 和逐步持久化的 `GenerationStep`。
- OpenAI 兼容 LLM Provider 与明确标记的 Mock LLM Provider。
- Sports Short Video Full Package 十步工作流。
- Prompt 安全预览、变量 Schema 校验、工作区权限、CSRF、幂等运行。
- 确定性字符数、单行 TTS、证据状态和最终输出 Schema QA。
- 自动重写上限、手动重写新运行、保存/采用、JSON/TXT 导出。
- Token 来源、估算成本、运行耗时、错误和系统事件记录。

## 2. 初始化顺序

先初始化管理员并导入、发布完整 7.9 规则，再执行：

```powershell
docker compose run --rm api python -m app.cli seed-generation
```

种子来自 `data/prompts/sports_short_video_full_package.json`。业务 Prompt 不存放在 Python 常量中。命令幂等，并把工作流默认规则固定到当前已发布的完整 7.9 版本。

## 3. 十步工作流

1. Research Input：冻结内部新闻、事件、作品或用户输入及来源。
2. Normalize Facts：将输入声明拆为事实候选并关联证据。
3. Build Timeline：区分事件时间、发布时间和未知时间。
4. Story Qualification：保存可解释的编辑判断。
5. Apply Rules：固定 7.9 版本并按强制性、优先级编译步骤规则包。
6. Generate Draft：调用指定 Provider 生成一行英文 TTS。
7. Editorial Review：执行空输出和 Mock 标记等确定性审查。
8. QA Validation：校验参数化字符范围、单行和事实核实状态。
9. Automatic Rewrite：只根据 findings 重写，达到配置上限后失败。
10. Final Formatting：生成事实摘要、来源、TTS、翻译、双语标题、搜索/素材词、标签、工程文件名和 QA 包。

每一步有独立状态、输入、输出、Prompt 快照、开始/结束时间和安全错误。历史运行固定 Rule/Prompt/Workflow/模型参数，不会被后续版本修改。

## 4. 真实性边界

- 内部新闻/事件证据来自已冻结数据库记录；Research 不会让 LLM 自称使用了不存在的浏览器或搜索工具。
- 单篇新闻、作品或用户文本默认 `verification_incomplete`；至少两个不同来源才会标记 `corroborated`。
- `mock_llm` 输出始终包含 `MOCK TEST OUTPUT`，运行元数据和最终包均标记 `mock`。
- OpenAI 兼容 Provider 的“已配置”健康状态只表示后端配置存在，不执行可计费探测。
- Provider 未返回 Token 或没有价格快照时，用量/成本保持 `unavailable`，不伪造精确成本。

## 5. 安全

- `SIO_LLM_OPENAI_COMPATIBLE_API_KEY` 只进入 API/Worker 环境，不保存到 Prompt、运行输入或前端响应。
- Prompt 预览递归脱敏 key/token/secret/password/cookie/authorization 字段。
- 外部文本被放入显式 `UNTRUSTED INPUT DATA` 区域，不能覆盖 System Prompt。
- 模型参数使用 allowlist；字符范围限制为 200–5000，自动重写最多五次。
- 兼容 Provider 有超时、有限重试、指数退避、429/认证/5xx/契约错误分类，响应正文不写入普通日志。

## 6. API

- `GET/POST /api/v1/prompts`
- `GET /api/v1/prompts/{collection_id}`
- `POST/GET/PATCH /api/v1/prompts/{collection_id}/versions/...`
- `POST .../publish`、`POST .../rollback`
- `GET /api/v1/workflows`
- `GET /api/v1/llm/providers`
- `POST /api/v1/generations/preview`
- `POST/GET /api/v1/generations`
- `GET /api/v1/generations/{run_id}`
- `POST .../retry`、`POST .../rewrite`、`PATCH .../decision`
- `GET .../export?format=json|txt`

写操作要求会话、工作区角色和 CSRF；创建运行支持 `Idempotency-Key`。

## 7. 已知限制

- 首期 Research 只使用系统已经持久化的输入和来源，不提供通用联网搜索工具。
- OpenAI 兼容 Provider 首期使用 Chat Completions JSON 模式，未实现流式输出和各厂商专有参数。
- 规则按强制性与优先级编译；为控制上下文，单个生成步骤最多注入 120 条，并记录截断状态。
- 没有价格参数时真实 Provider 成本不可用；Mock 成本固定为零。
- 高级 Workflow 图编辑、步骤恢复协调和对象存储属于后续增强。
