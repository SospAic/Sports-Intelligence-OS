# 语义检索新鲜度与可解释性

语义检索状态接口现在同时返回检索覆盖和索引新鲜度：

- `embedded_items` / `embedded_chunks`：当前 embedding 模型已经建立的内容和块数量；
- `pending_items`：有标题或描述、但尚未建立当前模型索引的内容数量；
- `latest_embedded_at`：当前工作区最近一次向量块生成时间；
- `freshness`：`fresh`、`stale` 或 `empty`；
- `freshness_detail`：面向运营人员的具体解释。

`stale` 只表示存在真实内容尚未进入当前模型索引，不会用估算值填充结果。页面显示“待补索引”并保留现有关键词降级路径；向量后端不可用时仍明确显示服务未启用/降级。

结果的 `debug=true` 路径继续返回向量、关键词、RRF/重排分和命中路径解释。字幕/转写命中保留 `start_ms`、`end_ms` 和 `source_ref`，可用于后续直接定位素材片段；本轮不把不存在的时间轴伪造为证据。

