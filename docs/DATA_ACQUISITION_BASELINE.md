# 数据采集基线（Data Acquisition Baseline）

> 本文件是 `AGENTS.md` 第 4.5 条的落地契约，定义**字段级**采集方式与"需要条件"提示规则。
> 生效日期：2026-08-01。它被 `docs/ACCOUNT_MONITORING_ANALYSIS.md`（账号监控指标颗粒度方案）与前端 `lib/metric-availability.ts` 直接引用。

## 1. 总原则

1. **模拟浏览公开渠道是账号 / 平台级数据的首要方式**，高于项目内部"删除 mock / 不得抓取"等自设限制，但不高于法律法规与平台条款。
2. **公开渠道能获取的数据必须上页**：只要适配器实际返回，就展示，不得用占位 / 未实现掩盖。
3. **需要 API / 登录授权的数据，若条件未满足，栏位显式渲染「需要：具体条件」**，而不是隐藏或伪造。
4. **合规边界**：不绕过验证码、不突破登录安全机制、不违反平台条款；登录墙场景适配器抛 `login_required`，前端展示「需要登录凭证」。

## 2. 采集方式（Acquisition Method）

| 方式 | 含义 | 是否需要额外条件 |
|---|---|---|
| `public_browse` | 匿名浏览器模拟公开页面即可获取 | 否（仅网络可达） |
| `api` | 需要官方 API Key / OAuth / 私有分析授权 | 是 |
| `login` | 需要平台登录凭证（账号密码 / Cookie / 授权会话） | 是 |
| `api_or_login` | API 或登录任一满足即可 | 是 |

## 3. 字段级契约（Field Contract）

> 「需要条件时 UI 文本」是栏位在**数据缺失且该方法需条件**时渲染的文案；一旦适配器实际返回该值，无论方式如何都直接展示数值（见第 4 节优先级）。

| 字段 | 实体 | 采集方式 | 需要条件时 UI 文本 |
|---|---|---|---|
| `follower_count` 粉丝数 | 账号 | `public_browse` | —（无） |
| `total_view_count` 总播放 | 账号 | `public_browse` | — |
| `video_count` 作品数 | 账号 | `public_browse` | — |
| `engagement_rate` 互动率 | 账号 / 作品 | `public_browse` | — |
| `title` / `cover_url` / `published_at` / `duration_seconds` | 作品 | `public_browse` | — |
| `view_count` 播放 | 作品 | `public_browse` | — |
| `like_count` 点赞 | 作品 | `public_browse` | — |
| `comment_count` 评论 | 作品 | `public_browse` | — |
| `share_count` 分享 | 作品 | `public_browse` | — |
| `favorite_count` 收藏 | 作品 | `public_browse` | — |
| `completion_rate` 完播率 | 作品 | `api` | 需要：配置该平台官方 API / 私有分析授权（完播率） |
| `average_watch_time` 平均观看时长 | 作品 | `api` | 需要：配置该平台官方 API / 私有分析授权 |
| `recommendation_traffic_rate` / `search_traffic_rate` / `profile_traffic_rate` 流量来源占比 | 作品 / 账号 | `api` | 需要：配置该平台官方 API / 流量来源授权 |
| `revenue` 变现收入 | 作品 | `api` | 需要：配置该平台变现 / 收益 API 授权 |
| `rpm` 每千次播放收益 | 作品 | `api` | 需要：配置该平台变现 / 收益 API 授权 |
| `search_terms` 搜索词 | 作品 | `api` | 需要：配置该平台官方 API / 搜索词授权 |

> 平台差异：YouTube Data API / YouTube Analytics、抖音巨量引擎、TikTok Analytics 等官方接口可供给 `api` 类字段；Bilibili / TikTok / 抖音的匿名公开页当前**不**暴露完播率、流量来源与变现，因此这些字段在上述平台默认进入"需要条件"状态，直到配置对应官方 API。若某平台公开页未来确实暴露该值，适配器返回后数值自动上页，无需改契约。

## 4. UI 渲染优先级（Rendering Precedence）

对每个指标栏位，前端 `metricAvailability(metricKey, hasValue)` 按以下顺序判定状态：

1. **有值 → `data`**：直接展示数值（含格式化与阈值着色）。公开数据永不因"方式受限"而被隐藏。
2. **无值 + 采集方式非条件类（`public_browse`） → `no-data`**：渲染「—」，表示"可获取但当前尚无观测"。
3. **无值 + 采集方式需条件（`api` / `login` / `api_or_login`） → `needs-condition`**：渲染「需要：<条件文本>」徽章（琥珀色），并链接到「设置 → 平台管理」说明如何满足。

> 这一优先级保证了第 2 条原则：已可获取的公開数据（即使其契约方式标为 `api`，只要适配器实际返回）一律展示；"需要条件"仅在**数据确实缺失且方法本身需要授权**时才出现。

## 5. 适配器能力声明的作用边界

适配器 `AdapterDescriptor.capabilities`（如 `RETENTION`、`TRAFFIC_SOURCES`、`REVENUE`）用于后端能力矩阵展示，但**不**用于前端"是否隐藏数据"的决策——前端以"实际返回值 + 第 3 节契约方式"为准。即：能力声明为 `False` 但适配器某次真实返回了值，该值仍上页（不截断）；能力声明为 `True` 但当前无值，按 `no-data` 处理。

## 6. 合规与来源

- 所有上页数据保留 `source_kind`（`live` / `imported`）；浏览器模拟数据标 `live`。
- 登录墙 / 验证码 / 平台条款限制下，不得强行突破；缺失数据以"需要条件"或"暂无"诚实呈现。
- Mock 数据仅用于自动化测试（契约测试），生产路径不使用，UI 不展示 `mock` 来源的真实平台指标。
