# 账号监控（Account Monitoring）功能点详细分析与指标颗粒度升级方案

> 文档目的：在「删除 mock + 真实数据链路 + 后端批量/对比/自适应频率」已完成的基础上，对账号监控做一次完整的功能点盘点，定位「作品清单看不到 / 指标颗粒度粗」的根因，并参考抖音创作者中心、YouTube Studio、B站创作中心、小红书创作中心、新榜/蝉妈妈等优秀产品的指标设计，给出颗粒度升级与实现方案。

---

## 1. 当前账号监控功能地图（已实现）

### 1.1 账号层（Account）
| 功能点 | 实现位置 | 现状 |
|---|---|---|
| 账号 CRUD + 平台绑定 | `monitoring.py` routes + `AccountRead` | ✅ 完整 |
| 单账号同步（手动触发） | `POST /accounts/{id}/sync` | ✅ 支持，仅 `implementation_status=implemented` 平台可点 |
| 自适应采集频率（优化B） | `POST /accounts/{id}/sync-interval` + `adaptive_sync.py` | ✅ 按发布中位间隔算 `sync_interval_seconds`（300s 下限） |
| 批量启用/停用 | `PATCH /accounts/batch` | ✅ P1-6 已完成 |
| 批量删除（软删） | `POST /accounts/batch/delete` | ✅ P1-6 已完成 |
| 批量同步 | `POST /accounts/batch/sync` | ✅ P1-6 已完成 |
| 跨平台对比聚合 | `GET /accounts/compare` | ✅ P2-2 已完成（粉丝/播放/作品/互动 + 增量） |
| 账号快照历史 + 趋势图 | `GET /accounts/{id}/snapshots`、`/metrics/history` | ✅ 30/90/180/365 天切换 |
| 同步记录（含阶段进度） | `GET /accounts/{id}/sync-runs` | ✅ 含 queued→content_list→content_metrics→derived_metrics 阶段条 |
| 导出 CSV | `GET /accounts/export.csv` | ✅ |

### 1.2 作品层（Content）
| 功能点 | 实现位置 | 现状 |
|---|---|---|
| 作品列表（独立页） | `GET /contents`、`apps/web/app/contents` | ✅ 富表格（TanStack Table），支持搜索/平台/最低播放/发布时间筛选、多选、CSV 导出 |
| 账号下作品 | `GET /accounts/{id}/contents` | ✅ 接口在，但**前端详情「作品」tab 极简** |
| 单作品详情 | `GET /contents/{id}` | ✅ |
| 单作品快照时序 | `GET /contents/{id}/snapshots` | ✅ 后端已落库全量指标 |
| 单作品派生指标 | `GET /contents/{id}/metrics` | ✅ `view_growth_1h/6h/24h` |

### 1.3 后端已采集、但前端几乎没展示的「细颗粒度」字段
`ContentSnapshot` 模型已存（来自适配器 `fetch_content_analytics`）：
- `view_count / like_count / comment_count / share_count / favorite_count`
- `average_watch_time`（平均观看时长）、`completion_rate`（完播率）
- `search_traffic_rate / recommendation_traffic_rate / profile_traffic_rate`（流量来源占比）
- `revenue / rpm`（变现）
- `follower_gain`

`AccountSnapshot` 已存：`follower_count / total_view_count / video_count / engagement_rate`。

**结论：数据底座够用，缺口在「前端展示层 + 排序/筛选维度 + 时间范围」。**

---

## 2. 「作品清单看不到」根因诊断

1. **空状态优先（最主要）**：`account-detail-client.tsx` 的「作品」tab 渲染逻辑是 `contents.data?.items.length ? 列表 : 尚无作品`。在没有任何真实同步内容的环境（开发/演示/未配凭证）下，必然显示「尚无作品」，给人"看不到"的观感。
2. **作品 tab 颗粒度过低**：即便有数据，当前只渲染 `封面 + 标题 + 发布日期 + 播放量`，缺少互动拆解、完播率、流量来源、单作品趋势——视觉上"不像作品监控"，更像占位。
3. **排序维度不足**：账号下作品查询复用 `ContentSort`，仅支持 `published_at / first_seen_at / last_seen_at / title / view_count / view_growth_24h`，**不能按点赞/评论/互动率/完播率排序**，无法做"爆款优先"视图。
4. **无时间范围**：作品 tab 不接时间范围选择器（P2-1 尚未实现），无法看"近 7 天发了什么、涨了多少"。

> 注：所有 7 个平台适配器都标记为 `implemented` 且实现了 `list_contents`，因此"看不到"不是接口缺失，而是**空数据 + 展示过简**的组合问题。

---

## 3. 竞品指标颗粒度基准（调研结论）

| 维度 | YouTube Studio | 抖音/蝉妈妈 | B站创作中心 | 小红书创作中心 | 新榜/蝉妈妈（对标） |
|---|---|---|---|---|---|
| 实时/近况 | 48h 实时播放、实时观众数 | 发布后 24–48h 黄金监测期 | 分钟级稿件监控 | 48h 流量监控 | 分钟级刷新 |
| 播放/曝光 | Views、Impressions、Unique Viewers | 播放量（平均+趋势）、曝光 | 播放、弹幕 | 曝光量、阅读量、点击率 | 平均播放、爆款率 |
| 互动拆解 | 点赞/评论（含踩）、End screen CTR | 点赞率/评论率/转发率/收藏率（各占播放比） | 点赞/投币/收藏/分享/弹幕/充电 | 点赞/收藏/评论/转发（互动率 5–15%） | 互动率、爆款率 |
| 完播/观看 | Audience Retention 曲线、AVD、平均观看% | **完播率（前3秒/整体）、5秒完播率、平均观看时长** | 完播率、粉丝转化 | 完读率 | 完播率 |
| 流量来源 | Search/Suggested/Browse/External/Playlist 拆分 | 推荐占比(>40%健康)/搜索/关注/其他 | — | 首页推荐占比(≥60%优)/搜索 | 流量结构 |
| 粉丝/人群 | 回看率 vs 新观众、年龄/性别/地域/设备、订阅来源 | 粉丝净增、涨粉率、性别/年龄/地域/活跃时段 | 粉丝转化 | 粉丝画像、涨粉率 | 粉丝量级、粉丝画像 |
| 变现 | RPM、Revenue、Watch time from subs | GMV、转化率、客单价、UV价值 | 充电 | — | 带货销售额/销量 |
| 对标/榜单 | Advanced mode 对比、CSV 导出 | 同赛道竞品横向对比、行业均值 | 达人榜 | 同选题对比 | 跨平台榜单、自定义榜单、行业对标 |
| AI 诊断 | Quick Actions 瓶颈推荐 | AI 拆解爆款、数据智能解读 | — | AI 优化建议（标题/健康度/发布时间） | AI 达人匹配 |

**可借鉴的高价值颗粒度（本项目当前缺失或弱）：**
- 前 3 秒/整体完播率 + 平均观看时长（短视频核心）
- 互动率拆解到「赞/评/藏/转」各自占播放比
- 流量来源占比（推荐/搜索/关注/外部）——后端已采 `recommendation/search/profile_traffic_rate`，**直接可用**
- 近 24–48h 实时增量（后端已有 `view_growth_1h/6h/24h` 派生指标）
- 时间范围选择器驱动所有图表（P2-1）
- 爆款率 / 平均播放 等对标口径（可基于已有数据算）

---

## 4. 差距分析（Gap）

| 类别 | 现状 | 目标（参考竞品） |
|---|---|---|
| 作品列表展示 | 标题+封面+播放 | 富表格：封面+标题+发布+播放+点赞+评论+完播率+互动率+流量来源标签+趋势迷你图 |
| 作品排序 | 仅时间/播放 | + 按互动率、完播率、点赞、评论、涨粉排序 |
| 作品筛选 | 独立页有（平台/最低播放/时间），详情 tab 无 | 详情 tab 也支持按指标阈值/时间范围筛选 |
| 账号概览 | 粉丝/总播放/作品数/互动率 + 粉丝趋势 | + 流量来源占比环图、近 24h 实时增量、完播率/平均观看时长卡 |
| 时间范围 | 仅账号历史 4 档 | 全局时间范围选择器（P2-1），作品+账号共用 |
| 流量来源 | 已采集未展示 | 账号/作品双层级展示占比 |
| 对标 | 跨账号 compare API 已有 | 接入「同量级均值」基线、爆款率 |

---

## 5. 指标颗粒度升级方案（落地映射）

### 5.1 不改动后端即可做（字段已存在，仅前端展示）
- **账号详情「作品」tab**：从极简列表升级为 `DataTable`（复用 `apps/web/app/contents` 的表格组件与列定义），列包括：封面、标题、平台、发布时间、播放、点赞、评论、完播率、互动率、流量来源标签、近 24h 增量（迷你 sparkline）。数据来自 `ContentRead.latest_snapshot`（已含 like/comment/completion_rate/traffic rates）。
- **账号概览**：新增「流量来源占比」用小条形/环图展示 `search/recommendation/profile_traffic_rate`（取最新账号快照或聚合作品）；新增「完播率 / 平均观看时长」卡（从作品聚合）。
- **单作品详情页**：新增互动拆解卡 + 流量来源卡 + 完播率 + 近况增量。

### 5.2 需要小改后端（低风险）
- 扩展 `ContentSort` 增加 `like_count / comment_count / engagement_rate / completion_rate`（在 repository `order_by` 映射里 JOIN 最新快照即可；现有 `view_growth_24h` 已证明此模式可行）。
- `GET /accounts/{id}/contents` 当前排序支持复用同一枚举。
- 账号概览聚合：新增 `GET /accounts/{id}/content-summary`（聚合该账号作品的完播率均值、互动率均值、流量来源加权占比、近 24h 增量）——可选，也可前端用现有列表聚合。

### 5.3 指标口径（建议统一）
- **互动率** = (点赞+评论+分享+收藏) / 播放，分平台阈值：抖音/小红书 5–15% 为优，低于 3% 预警。
- **完播率**：短视频核心，前 3 秒完播率（若平台提供）单列；整体完播率 < 15% 标红。
- **流量来源健康度**：推荐占比 ≥ 40%（抖音）/ 首页推荐 ≥ 60%（小红书）为健康；搜索占比高=标签精准（长效）。
- **爆款率** = 近 N 天播放 ≥ 账号均值 3 倍的作品占比。
- 所有展示指标必须保留 `source_kind`（live/imported）标识，禁止冒充真实平台数据（AGENTS.md 红线）。

---

## 6. 实现方式（Implementation Approach）

**分层原则（AGENTS.md 强制）**：平台适配器 ↔ 统一模型 ↔ 规则/指标计算 ↔ Web 服务 分离；指标计算进 `metric_calculations.py` / service，不在前端硬算业务口径。

1. **前端组件复用**：`apps/web/components/data-table.tsx` + `apps/web/app/contents` 的列定义，直接复用到账号详情「作品」tab，避免重复造轮子。
2. **时间范围选择器（P2-1）**：抽成 `components/time-range-picker.tsx`，账号历史、作品列表、概览图共用；值写入 query param（`published_from/published_to` 或 `days`）。
3. **指标展示组件**：新建 `components/metric-breakdown.tsx`（互动拆解）、`components/traffic-source.tsx`（来源占比）、`components/sparkline.tsx`（迷你趋势），均为纯展示、数据来自已有 API。
4. **后端排序扩展**：在 `app/schemas/monitoring.py` 的 `ContentSort` 增加键，`app/repositories/monitoring.py` 的 `list_contents` 增加 JOIN 最新快照的 `order_by` 分支（与现有 `view_count` 排序同构）。
5. **真实数据链路验证**：用 `RealShapedTestAdapter`（`content_count=12`，`view_offset` 驱动增量）+ `StubLLMProvider` 跑契约测试，作品指标断言完播率/互动率非空、`source_kind=live`；不伪造、不 mock 成功。
6. **质量门禁**：每步 `tsc / eslint / vitest` + 后端 `pytest / ruff / mypy`，批量提交抗沙箱清空。

---

## 7. 优先级与里程碑（建议）

| 优先级 | 项 | 价值 | 工作量 |
|---|---|---|---|
| P0（修症状） | 账号详情「作品」tab 升级为富表格 + 空状态引导文案 | 直接解决"看不到作品清单" | 中 |
| P0 | 前端展示流量来源/完播率/互动率（字段已采） | 解决"颗粒度粗" | 小 |
| P1 | 时间范围选择器 P2-1（作品+账号共用） | 竞品标配 | 中 |
| P1 | ContentSort 扩展（互动/完播排序） | 爆款优先视图 | 小（后端） |
| P2 | 账号概览聚合卡（完播/观看时长/来源占比） | 决策层 | 中 |
| P2 | 单作品详情增强（互动拆解+来源+近况） | 深度诊断 | 中 |
| P3 | 对标基线（同量级均值/爆款率） | 竞品对标 | 大 |

---

## 8. 下一步

本方案第 5.1/5.2/6 节可直接进入实现。建议按 P0 → P1 → P2 推进，复用既有 `DataTable` 与已采集字段，后端改动保持在 repository 排序映射层级，不触碰适配器与红线约束。所有新增展示指标均带 `source_kind` 标识。
