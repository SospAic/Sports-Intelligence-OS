# 生成证据包

生成运行现在提供只读接口 `GET /api/v1/generations/{run_id}/evidence`。接口按工作区隔离，从生成运行已经持久化的冻结输入和工作流步骤输出组装证据包，不会重新调用模型、新闻源或平台接口。

## 返回内容

- `input_hash`、`frozen_at`、`source_kind`：用于确认本次生成使用的输入快照；
- `sources`：冻结输入中实际提供的来源，保留 `source_id`、来源类型、Provider、URL 和其他原始字段；
- `claims`：事实归一化步骤产生的声明及其 `evidence_ids`；
- `timeline`、`qualification`：时间线和选题判定步骤的持久化结果；
- `step_statuses`：每个工作流步骤的完成状态与来源引用；
- `output_references`：成品事实摘要、来源和核实状态与来源 ID 的关联。

## 核实状态

`evidence_status` 只反映冻结输入中的真实来源：

- `unavailable`：没有来源，核实状态保持未完成；
- `partial`：有来源，但没有达到交叉核实条件；
- `available`：运行核实状态为 `corroborated`，且至少有两个不同的 `source_id`。

这不是对事实正确性的二次判断，也不会把模型生成的文本当作来源。用户导入文本没有独立来源时，接口会明确返回 `unavailable`。
