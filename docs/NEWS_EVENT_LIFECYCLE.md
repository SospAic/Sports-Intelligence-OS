# 热点事件生命周期与榜单去重

## 目的

热点事件不是一次聚类后的静态记录。系统需要根据最近一次可追溯观测持续更新事件状态，并在分析榜单中避免把追加式历史观测重复计入。

## 生命周期规则

后台任务 `app.tasks.news.refresh_event_lifecycles` 每 5 分钟扫描活跃工作区中的 `active` 和 `developing` 事件：

- `active`：距 `last_update_time` 小于 24 小时；
- `developing`：距 `last_update_time` 大于等于 24 小时且小于 72 小时；
- `closed`：距 `last_update_time` 大于等于 72 小时。

生命周期评估写入事件 `metadata.lifecycle`，包括算法版本、阈值、评估时间和观测年龄。已关闭事件不会被后台任务静默重新打开；如新资料需要重新建模，应通过新的事件/合并流程保留审计链。

管理员和工作区所有者可调用 `POST /api/v1/news/events/lifecycle/refresh` 立即刷新当前工作区。事件列表支持 `status=active|developing|closed` 筛选，前端事件中心同步显示状态筛选和生命周期列。

## 榜单去重规则

榜单的事件级读模型使用以下实体键：

```text
workspace_id + normalized_title + lower(sport) + lower(league)
```

同一工作区内只有同一规范标题、同一项目、同一联赛的事件会被压缩为一条；不同项目或联赛即使标题相同，也不会被误合并。原始文章、事件关系和历史快照不会被删除，读模型只选择最新代表记录。

## 数据边界

生命周期只依据已持久化的 `last_update_time`，不把抓取时间冒充发布时间，也不推算缺失指标。排行榜仍依赖来源和指标审计字段；没有真实平台授权的账号级字段继续显示具体条件，而不是以 Mock 值替代。

## 验证

本功能已通过：

- Ruff 与 mypy；
- 生命周期状态转换、关闭事件不自动重开、事件 API 回归测试，共 7 项；
- Docker API/Worker/Beat 镜像构建与 Compose 重启；
- Alembic `20260817_0004 (head)` 和 `alembic check`。

