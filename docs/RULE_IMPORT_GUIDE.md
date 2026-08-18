# 7.9 规则导入、版本与编辑指南

文档状态：Prompt 06 已实现  
更新时间：2026-07-26

## 1. 已导入源文件

本阶段使用用户提供的完整文件：

`data/rules/ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt`

完整文件属性：

- 字节数：311,594；
- 行数：1,856；
- SHA-256：`9f69ee764fc9c33217699df584bba18ecd5d584af8ada3770e5c8779f9e824d6`；
- `source_status`：`full`；
- 解析结果：816 个章节节点、1,021 条规则。

SHA-256 按原始文件字节计算。`RuleSetVersion.source_text` 保留完整原文，`source_hash` 保存完整字节哈希；每条结构化规则通过 `source_reference=lines:start-end` 追溯原文位置。结构化规则不是原文的替代品。

## 2. 导入命令

先执行迁移并创建管理员，再运行：

```bash
make import-rules FILE=data/rules/ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt
```

等价 Docker Compose 命令：

```bash
docker compose run --rm api python -m app.cli import-rules --file data/rules/ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt
```

不使用 Docker 时，从 `apps/api` 执行：

```powershell
....\.venv\Scripts\python.exe -m app.cli import-rules --file ..\..\data\rules\ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt
```

导入按 `workspace + rule_set_key + source_hash` 幂等。相同完整原文重复导入返回现有版本，不创建重复结构。

## 3. 确定性解析边界

解析器识别文档前言、29 个 Kernel、20 个 Part、编号子章节和 195 项测试。每个节点获得稳定 key、排序、规则类型、强制性、严重级别、标签和原文行号。

只有原文明示 `WHY:`、`HOW:`、`GOOD EXAMPLE:`、`BAD EXAMPLE:`、`QA:` 或 `REWRITE:` 时，解析器才填充对应字段。它不会用模型推断或虚构缺失内容。测试条目自身写入 `qa_check`；其他缺少独立 QA 的规则会产生 `missing_qa` 警告。本次完整导入有 826 项此类非阻断警告，它们是后续人工整理队列，不表示原文缺失。

空的 `sports`、`story_types` 和 `output_types` 表示没有额外缩小适用范围。依赖与冲突不会从普通交叉引用中臆测；用户可在草稿编辑器明确配置。

## 4. 版本语义

- `draft`：允许修改结构化字段、批量启停和运行校验。
- `published`：不可原地修改。编辑已发布规则时，服务端自动完整复制为新的 `*-draft.N` 草稿，再把修改应用到新版本。
- `archived`：只读，不允许发布或编辑。
- 发布：完整校验无阻断错误后设置为当前版本；历史发布版本保持不可变。
- 回滚：只把 `RuleSet.current_version_id` 指回指定历史发布版本，不改写任何历史版本。
- 原文：结构化编辑不会覆盖 `source_text` 或 `source_hash`。

所有创建、导入、规则修改、批量修改、发布和回滚均写入 `audit_entries`。

## 5. 规则验证

阻断发布的错误包括：

- 必填字段缺失；
- 重复规则 key；
- 不存在的依赖或冲突目标；
- 循环依赖；
- 同一目标既依赖又冲突；
- 互相冲突的规则同时启用；
- 缺失章节；
- `source_status=unresolved` 或没有原文引用；
- 强制规则被禁用。

缺少独立 QA 当前是警告，不阻断忠实导入原始规则。编辑者可以逐步补充 QA 后创建新版本。

## 6. API

基础路径为 `/api/v1/rules`，所有资源由当前认证工作区隔离。写操作需要 CSRF Token；编辑需要 Owner/Admin/Editor，发布和回滚需要 Owner/Admin。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET/POST | `/rules` | 列表、创建规则集合 |
| POST | `/rules/import` | 导入 UTF-8 TXT 或 JSON 规则包 |
| GET | `/rules/{set}` | 集合与版本历史 |
| POST | `/rules/{set}/versions` | 从指定/当前版本创建草稿 |
| GET | `/rules/{set}/versions/{version}` | 版本、原文及统计 |
| GET | `/rules/{set}/versions/{version}/tree` | 完整章节树和结构化规则 |
| GET | `/rules/{set}/versions/{version}/rules` | 搜索、类型、强制、启用与标签筛选 |
| PATCH | `/rules/{set}/versions/{version}/rules/{rule}` | 单条编辑；发布版自动复制草稿 |
| PATCH | `/rules/{set}/versions/{version}/rules` | 批量编辑 |
| POST | `/rules/{set}/versions/{version}/validate` | 运行完整校验 |
| POST | `/rules/{set}/versions/{version}/publish` | 发布草稿 |
| POST | `/rules/{set}/versions/{version}/rollback` | 回滚当前指针 |
| GET | `/rules/{set}/compare?left=&right=` | 字段级差异 |
| GET | `/rules/{set}/versions/{version}/export?format=txt|json` | 导出 |

JSON 导出包含 schema 版本、规则集合元数据、原文、原文哈希、章节和全部结构化字段。重新导入时必须通过 Pydantic schema 与原文哈希校验。

## 7. 前端页面

- `/rules`：规则集合与版本统计；
- `/rules/{ruleSetId}`：版本、状态、哈希和导出；
- `/rules/{ruleSetId}/versions/{versionId}`：原文、结构化和 JSON 三种视图；
- `/rules/{ruleSetId}/edit`：左侧章节树/过滤，中间规则正文，右侧属性与 QA；
- `/rules/{ruleSetId}/compare`：两版本字段差异；
- `/rules/import`：本地 TXT/JSON 文件导入。

所有保存、校验、发布、回滚、比较和导入按钮调用真实后端 API，并显示错误结果。

## 8. 已知限制

- 当前是确定性标题/编号解析，不执行语义级规则合并；Why、How、示例和关系需在原文明示或由编辑者审核补充。
- 规则树首期一次加载完整版本；若未来单集合达到数万规则，需要改为按章节懒加载。
- 本地迁移和契约验证使用本地 Docker PostgreSQL；PostgreSQL 是唯一生产数据链路，系统已移除 SQLite。
- Prompt 模板、LLM Provider 与十步内容生成工作流已经实现；默认工作流只有在规则版本发布并执行 `make seed-generation` 后才会引用 7.9 规则。

## 9. 首次交付验收

导入后应在 `/rules` 确认原文哈希、章节数和规则数，创建一条草稿修改并保存为新版本，再验证发布版本没有被原地修改。自动化测试覆盖完整原文追踪、重复导入幂等、编辑、发布、对比和回滚；不得通过直接修改已发布数据库行绕过版本 API。
