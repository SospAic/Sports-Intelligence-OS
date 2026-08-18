# 发布记录与固定窗口表现归因

## 目标

发布记录把“准备发布”“已登记外部作品”和“已由监控快照验证的表现”分开，避免把计划记录或人工填写的链接误显示为平台 Adapter 已经成功发布。归因只读取 `ContentSnapshot` 中已经存在的真实观测，不生成估算指标。

## 数据模型

- `publications`：工作区、内容生成/审核来源、监控作品、账号/平台、状态、发布时间、平台作品 ID/链接和来源证据。
- `performance_attributions`：每条发布记录的固定窗口状态和指标，窗口为 `1h`、`3h`、`6h`、`24h`、`72h`、`7d`、`30d`。
- 所有外部来源保留 `source_kind`、`source_provider`、`source_url`；实测窗口的 `evidence` 会记录内容快照 ID、目标时间、捕获时间、偏移秒数和选择策略。

固定窗口选择策略为：取目标时间之后、24 小时宽限期以内的第一条真实快照。目标时间尚未到达时为 `not_due`；已到达但没有符合条件的快照时为 `unavailable`。这两种状态均不填入指标数值。

## API

- `GET /api/v1/publications`：按状态或监控作品分页查询。
- `POST /api/v1/publications`：登记计划、排期、人工导入或待核实记录；已发布记录必须同时提供 `published_at` 和平台作品 ID/链接。
- `GET /api/v1/publications/{id}`：返回固定窗口归因和证据。
- `PATCH /api/v1/publications/{id}`：执行受控状态变更，已关联监控作品不可替换。
- `POST /api/v1/publications/{id}/attribution/refresh`：重新读取现有内容快照并更新七个固定窗口。

写入会记录 `publication.created`、`publication.updated` 和 `publication.attribution_refreshed` 审计事件，并按工作区隔离来源对象。

## 前端入口

管理后台“创作 → 发布记录”提供登记表单、状态筛选、来源标记、固定窗口表格和证据摘要。刷新按钮仅在存在发布时间和关联监控作品时启用；缺失快照、未到窗口或需要外部授权的指标会显示明确状态，不显示占位成功值。

## 边界

当前实现不声称已接入任何平台排期/发布 Adapter，也不绕过登录墙、验证码或平台限制。后续接入官方授权 Adapter 时，应由 Adapter 返回外部作品 ID、规范链接和发布回执，再将 `source_kind=live` 写入记录；私有分析字段仍需对应平台 API 或登录授权。

