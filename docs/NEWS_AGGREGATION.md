# 体育新闻聚合系统

文档状态：Prompt 05 已实现  
更新日期：2026-07-25

## 1. 领域边界与数据表

News Context 独立于账号监控，使用：

- `news_sources`：工作区级 RSS、Atom、JSON 和手动来源配置；
- `articles`：规范化文章、来源追踪、发布时间与去重组；
- `topic_events`：多篇文章聚合出的事件及热度/编辑评分；
- `event_articles`：事件与文章的带匹配分数连接；
- `news_sync_runs`：同步状态、计数、错误和单来源锁；
- `news_scoring_configs`：热度权重、衰减和相似度阈值的版本化配置。

所有实体按工作区隔离。Article 同时保留 `source_kind`、`source_provider`、`source_url`、`external_id`、`fetched_at` 和可选原始响应引用。RSS/Atom/JSON 同步标记 `live`；手动录入标记 `imported`。系统不会将 `fetched_at` 写入缺失的 `published_at`。

## 2. Provider

`NewsProvider` 统一提供 `validate_source`、`fetch_latest`、`fetch_range`、`normalize_article` 和 `health_check`。

| Provider key | 能力 | 边界 |
| --- | --- | --- |
| `rss` | RSS 2.x 下载、分页、时间范围、规范化 | 只保存 Feed 实际提供的字段 |
| `atom` | Atom 下载、分页、时间范围、规范化 | 不抓取链接页全文 |
| `generic_json` | 可配置 items path 和字段映射 | 不允许把 Token/密码写入配置 |
| `manual_news` | 用户提交文章规范化 | 不支持轮询，固定 `imported` |

网络 Provider 使用 HTTPX 超时、有限重试和指数退避，并分类认证、429、5xx、传输、配置与契约错误。默认不跟随重定向；来源 URL 拒绝 localhost、`.local` 和非公网 IP 字面量。配置递归拒绝 password、secret、token、api_key、authorization 和 cookie 类键，等待后续 Secret Resolver。

## 3. URL、正文与时间真实性

- URL 统一小写 scheme/host、移除 fragment、排序查询参数，并剔除 `utm_*`、`fbclid`、`gclid` 等跟踪参数。
- HTML 摘要仅转为纯文本；单条摘要和正文有长度上限。
- RSS/Atom 的 `published/updated` 才能成为 `published_at`；缺失时保持 `null`。
- `fetched_at` 始终是本系统取得 Feed/JSON 条目的时间，不能冒充事件发生或新闻发布时间。
- 初始同步不访问文章链接页，因此不会绕过站点访问控制或复制未在 Feed 中提供的全文。

## 4. 去重与事件聚类

去重依次检查：

1. 同来源 `external_id` 唯一，重复同步更新同一 Article；
2. 规范 URL 相同；
3. 规范标题与摘要的 SHA-256 内容哈希相同；
4. 在配置的标题相似度阈值之上，使用 token Jaccard 与 SequenceMatcher 的较高值。

跨来源副本共享 `duplicate_group_id`，原文仍分别保留以便来源与更新时间审计。基础事件聚类在最近 72 小时候选事件中按运动项目和标题相似度匹配；没有候选时创建新 TopicEvent。自动关系保存匹配分数和 `linked_by=automatic`。

编辑者可合并两个以上事件、将部分文章拆为新事件、收藏事件为选题，并按发布时间、抓取时间、热度、可靠度、来源数和编辑评分排序。合并后的原事件关闭并保留 `merged_into`；拆分时原事件必须至少保留一篇文章。

## 5. 参数化热度

默认配置作为 `news_scoring_configs` 第 1 版写入数据库，不把权重散落到事件逻辑：

```text
heat_score =
  source_weight        × average_source_reliability
+ freshness_weight     × half_life_decay
+ source_count_weight  × min(source_count / saturation, 1)
+ article_count_weight × min(article_count / saturation, 1)
+ user_interest_weight × bookmarked
```

默认五项权重总和为 100，半衰期 12 小时。API 更新时必须继续总和为 100，并创建新版本、停用旧版本、重算现有事件。热度裁剪到 0–100。`controversy_score`、`visual_score`、`story_score` 首期只接受编辑输入；没有输入时为 0，不通过关键词猜测并伪装为事实。

## 6. API

全部位于 `/api/v1/news`，要求登录并按工作区隔离：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST/GET | `/sources` | 创建与分页管理来源 |
| GET/PATCH/DELETE | `/sources/{id}` | 详情、更新、停用且保留历史 |
| POST | `/sources/{id}/sync` | 最新或指定时间范围同步，返回 202 |
| GET | `/sources/{id}/sync-runs` | 同步日志 |
| POST | `/articles/manual` | 手动录入 `imported` 新闻 |
| GET | `/articles` | 组合筛选、分页和八类排序 |
| GET | `/articles/{id}` | 新闻详情、来源、去重与事件信息 |
| GET | `/events`、`/events/{id}` | 热点列表与多来源事件详情 |
| POST | `/events/merge` | 手动合并事件 |
| POST | `/events/{id}/split` | 手动拆分事件 |
| PATCH | `/events/{id}/bookmark` | 收藏/取消选题 |
| GET/PUT | `/scoring-config` | 查看或发布下一版热度参数 |

文章筛选覆盖时间范围、运动、联赛、来源、语言、国家、关键词、重复状态、收藏状态和热度区间。事件筛选覆盖更新时间、运动、联赛、语言、国家、关键词、收藏和热度。

## 7. 默认来源示例

`python -m app.cli seed-news-sources` 创建三个默认停用的 ESPN 官方 RSS 配置示例和一个空的手动来源。ESPN 说明其 RSS 提供标题/摘要并要求链接与归因；种子记录该条款链接、默认停用，而且绝不执行下载或内置文章正文。启用前使用者仍需确认其使用场景符合来源条款。

## 8. 已知限制

- 首期为标题相似度聚类，没有实体抽取、跨语言向量或事件时间线自动推理。
- RSS/Atom 时间范围是在 Feed 当前可见窗口内过滤，不保证来源提供完整历史。
- 未实现文章详情页正文抓取、搜索 API、社交热点或视频平台热门内容。
- URL 防护会阻止直接私网地址，但完整 DNS 重绑定防护和出站代理策略仍需部署层补充。
- 本机未运行真实 Redis Worker/PostgreSQL 容器，也没有主动同步外部默认源；HTTP Provider 使用本地去敏契约响应验证。
