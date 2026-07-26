# 自动化使用指南

## 创建规则

普通用户通过可视化编辑器选择实体、字段、操作符和值，使用 AND/OR/NOT 嵌套。高级 JSON 视图仍会经过同一后端白名单和深度/节点限制校验。

示例：作品 `view_growth_1h gte 100000` 后依次创建选题、调用 Sports Short Video Full Package、发送通知。

## 动作

- `create_topic`：保存可追踪选题。
- `create_generation`：固定工作流、规则/Prompt 版本和 Provider，生成失败会记录错误。
- `notification` / `webhook`：通过绑定渠道创建投递记录。
- `save_content`、`external_api`：使用相同动作隔离机制。

渠道凭证必须保存在通知渠道，不得嵌入动作配置。

## 防重复语义

- `deduplication_window`：同一规则、实体和时间桶只执行一次。
- `cooldown_seconds`：命中后在实体级冷却。
- `consecutive_matches`：状态持久化，缺失字段使用三值逻辑，不误判为命中。
- `regex`：模式最长 256 字符，拒绝嵌套量词、反向引用和高风险量化分支；被检查文本最多 10,000 字符。
- 动作逐个隔离；部分失败状态为 `partial`。

Mock 数据默认被阻止触发生产动作。只有测试请求显式设置 `test_mode=true` 或规则计划明确 `allow_mock` 时才能验证 Mock 链路，所有记录仍保留 `source_kind=mock`。

## 排查

从自动化详情查看求值解释和动作结果，从通知渠道查看投递状态，从生成记录查看十步执行，从系统日志查看安全错误摘要。不要通过重复点击规避冷却或去重。任务超过执行租约时会释放锁或保留失败记录，不应通过直接修改数据库状态“解锁”。
