# 统一账号与作品模型

文档状态：Prompt 03 已实现  
更新日期：2026-07-25

## 1. 模型边界

Monitoring Context 使用六张业务表：`platforms`、`accounts`、`account_snapshots`、`content_items`、`content_snapshots`、`derived_metrics`。平台是全局目录；账号、作品和派生指标归属工作区。账号和作品的内部 UUID 与平台 `external_id` 分离。

平台专有低频字段进入 `metadata`，但账号身份、发布时间、计数、比率、流量来源、收益和时间序列字段均为结构化列。SQLAlchemy 属性使用 `metadata_json` 避开框架保留名，对外 API 仍返回 `metadata`。

## 2. 来源真实性

账号、作品和快照包含：

- `source_kind`：`live`、`imported` 或 `mock`；
- `source_provider`：实际 Adapter/导入器键；
- `external_id`：适用时的外部标识；
- `fetched_at`：系统取得该观察值的时间；
- `source_url` 和 `raw_payload_ref`：适用时记录来源或原始响应引用。

手动创建账号固定标记为 `imported/manual`，客户端不能通过 `metadata` 覆盖来源字段。Prompt 04 同步成功后，Adapter 观察值会使用 Adapter 固定的 `live` 或 `mock` 来源；不会根据平台名称猜测来源。

## 3. 快照与指标

- `(account_id, captured_at)` 和 `(content_item_id, captured_at)` 唯一。
- 应用层只暴露新增快照方法；SQLAlchemy 在更新快照前直接拒绝操作。
- 删除账号 API 实际执行停用，保留账号、作品和历史快照。
- 计数列必须非负，比率列必须位于 0–1。
- 时间序列使用实体 ID + `captured_at` 组合索引。

`derived_metrics` 支持：`view_growth_1h`、`view_growth_6h`、`view_growth_24h`、`follower_growth_24h`、`engagement_rate`、`share_rate`、`favorite_rate`、`view_velocity`、`view_acceleration`、`median_views_30d`、`account_baseline_ratio`、`viral_score`。每条值保留窗口、计算时间和算法元数据；Prompt 04 才负责定时计算。

## 4. API

全部路径位于 `/api/v1`，要求登录。多工作区用户必须提供 `X-Workspace-Id`；单工作区用户自动选择唯一活动工作区。写操作要求 CSRF Token 和相应角色。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/platforms` | 平台目录 |
| POST/GET | `/accounts` | 手动登记账号、分页列表 |
| GET/PATCH/DELETE | `/accounts/{id}` | 详情、编辑、停用 |
| POST | `/accounts/{id}/sync` | 创建/复用可审计同步任务并返回 202 |
| GET | `/accounts/{id}/sync-runs` | 最近同步状态、计数和安全错误摘要 |
| GET | `/accounts/{id}/snapshots` | 历史快照分页 |
| GET | `/accounts/{id}/contents` | 账号作品分页 |
| GET | `/contents` | 全部作品分页 |
| GET | `/contents/{id}` | 作品详情 |
| GET | `/contents/{id}/snapshots` | 作品快照分页 |
| GET | `/contents/{id}/metrics` | 派生指标分页 |
| GET | `/accounts/export.csv` | 按当前筛选导出账号 |
| GET | `/contents/export.csv` | 按当前筛选导出作品 |

列表支持 `sort`、`order`、`page`、`page_size`、`platform`、`account`、`published_from`、`published_to`、`min_views`、`max_views`、`query` 中适用于该资源的参数。作品可按最新播放量或最新 24 小时增长排序。CSV 最多同步导出 10,000 行，超出时要求缩小筛选范围，并对 `= + - @` 开头的单元格做公式注入防护。

## 5. 种子数据

平台目录和 Demo 数据分开初始化：

```powershell
docker compose run --rm api python -m app.cli seed-platforms
docker compose run --rm api python -m app.cli seed-demo-monitoring
```

Demo 平台键为 `demo_mock`，Adapter 键为 `mock_platform`；账号、作品、快照和派生指标全部固定为 `source_kind=mock`，名称、描述和 `metadata.demo` 也显著标识为模拟数据。命令幂等，不会创建真实平台数据，也不能作为 YouTube 集成成功的证据。

## 6. 当前限制

- YouTube 只实现 Data API 的公开字段；私有 Analytics 字段明确不可用。
- TikTok、抖音和 Bilibili 当前为显式失败的 Adapter 骨架。
- API 目前使用页码分页；超大时间序列的游标分页在证据表明需要时增加。
- PostgreSQL 容器验证受本机缺少 Docker 限制；SQLite 已完成迁移升降级和 Alembic 模型差异检查，CI 负责 PostgreSQL 迁移。
