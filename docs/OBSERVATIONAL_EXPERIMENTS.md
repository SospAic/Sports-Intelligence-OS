# 观察性内容实验

Sports Intelligence OS 的内容实验用于记录标题、Hook、叙事顺序和缩略图等内容维度的真实发布表现。当前实现是“观察性对照”，不是随机 A/B 测试，也不会把相关性解释为因果关系。

## 业务边界

- 实验和变体均按工作区隔离，并保留创建、更新、关联变体和状态变更审计记录。
- 每个变体必须关联已监控作品或发布记录；关联发布记录后，报告只读取 `PerformanceAttribution` 中 `measurement_status=measured` 的固定窗口数据。
- 报告展示样本数、已测数量、平均播放、互动率、完播率、来源类型和发布/归因证据。
- 没有真实归因或窗口尚未到期时显示空值，不估算、不补 Mock 指标。
- 报告固定标记 `comparison_type=observational`，并显示不同发布时间、平台、受众和分发条件未校正等限制。

## API

- `GET /api/v1/content-experiments`：分页列出当前工作区实验。
- `POST /api/v1/content-experiments`：创建实验。
- `GET /api/v1/content-experiments/{id}`：读取实验和变体。
- `PATCH /api/v1/content-experiments/{id}`：更新假设或状态。
- `POST /api/v1/content-experiments/{id}/variants`：关联作品或发布记录。
- `GET /api/v1/content-experiments/{id}/report?window_key=24h`：读取观察性报告，窗口支持 `1h/3h/6h/24h/72h/7d/30d`。

## 前端入口

运营人员可从“观察性实验”页面创建实验、关联已发布记录、切换状态并查看 24 小时真实归因。页面明确提示该报告不能替代随机 A/B 实验。

## 后续升级条件

要实现真正的 A/B 或因果分析，需要授权 Analytics、实验分流/随机化、曝光日志、样本量与统计检验，并且必须单独定义实验协议和数据保留策略；在这些条件满足前，不应增加“提升由该变量导致”的结论文案。

