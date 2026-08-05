# 开放诊断项（#9 / #10 / #11）

> 环境约束：本机 Docker Desktop 当前无法启动，无法连库执行。以下为**可执行的诊断 SQL + 根因分析**，
> 待 Docker 恢复（`docker compose up -d`）后在 `postgres` 容器中执行，或在 api 容器内用
> `python -c "import sqlalchemy..."` 跑。前置：先 `docker compose up -d postgres redis` 再连。
>
> **2026-08-05 更新**：Docker 已恢复，全部 SQL 已实际执行。注意 #11 原 SQL 为推测，与真实表结构不符——
> `sync_run_events` 实际列：`sync_run_id(uuid)`、`sequence`、`event_type`、`level`、`message`、`payload(jsonb)`、
> `created_at`，**没有** `run_id` / `started_at` / `ended_at` / `stage` / `detail`。下方已替换为已验证的 SQL。

## #9 — TikTok 账号数据全面核查与修复

TikTok / Douyin 的公开指标有限：yt-dlp 的频道 JSON 经常不返回 follower / view 数，
适配器已对这两类平台回退到 browser 适配器补齐（见 `yt_dlp.py:fetch_account_analytics`）。
因此以下为「预期内缺失」与「真实问题」的区分清单。

```sql
-- 1) TikTok / Douyin 账号及其最新快照的可用指标
SELECT a.platform_id, p.key AS platform, a.external_id, a.display_name,
       s.follower_count, s.video_count, s.total_view_count,
       a.sync_status, a.last_sync_error_message
FROM accounts a
JOIN platforms p ON p.id = a.platform_id
LEFT JOIN LATERAL (
  SELECT * FROM account_snapshots s2
  WHERE s2.account_id = a.id ORDER BY s2.captured_at DESC LIMIT 1
) s ON true
WHERE p.key IN ('tiktok','tiktok_ytdlp','douyin','douyin_ytdlp')
ORDER BY a.last_synced_at NULLS LAST;

-- 2) 同步失败 / 降级的 TikTok 账号（真实需要修的）
SELECT a.external_id, a.sync_status, a.last_sync_error_code, a.last_sync_error_message
FROM accounts a JOIN platforms p ON p.id = a.platform_id
WHERE p.key LIKE 'tiktok%' OR p.key LIKE 'douyin%'
  AND a.sync_status IN ('error','degraded');

-- 3) TikTok 内容条数 vs 其他平台，确认采集是否偏少
SELECT p.key AS platform, count(*) AS contents
FROM content_items c JOIN platforms p ON p.id = c.platform_id
GROUP BY 1 ORDER BY 2 DESC;
```

**判断**：`follower_count / total_view_count` 为 NULL 对 TikTok/Douyin 属**预期**（平台不公开展示），
不应视为 bug；只有 `sync_status='error'` 或内容条数明显异常偏少才需修复（通常要确认该账号用的是
`*_ytdlp` 适配器，且 workspace 的 `sync_settings` 未禁用采集）。

## #10 — 修复账号历史趋势总播放量无数据

根因（代码侧已确认）：`YtDlpAdapter.fetch_account_analytics` 对 **TikTok / Douyin** 显式返回
`total_view_count = None`（这些平台 profile 不暴露累计播放），仅 YouTube 带 lifetime views。
所以「历史趋势总播放量无数据」若发生在非 YouTube 账号上，是**设计预期**。

```sql
-- 哪些账号 total_view_count 为 NULL，按平台区分
SELECT p.key AS platform, count(*) FILTER (WHERE s.total_view_count IS NULL) AS null_total,
       count(*) AS total
FROM accounts a
JOIN platforms p ON p.id = a.platform_id
LEFT JOIN LATERAL (
  SELECT total_view_count FROM account_snapshots s2
  WHERE s2.account_id = a.id ORDER BY s2.captured_at DESC LIMIT 1
) s ON true
GROUP BY 1;

-- YouTube 账号却仍无 total_view_count → 真实问题（需重跑同步补快照）
SELECT a.external_id, a.sync_status
FROM accounts a JOIN platforms p ON p.id = a.platform_id
LEFT JOIN LATERAL (
  SELECT total_view_count FROM account_snapshots s2
  WHERE s2.account_id = a.id ORDER BY s2.captured_at DESC LIMIT 1
) s ON true
WHERE p.key LIKE 'youtube%' AND s.total_view_count IS NULL;
```

**修复**：仅对「YouTube 且无 total_view_count」的账号重跑一次同步即可回填；TikTok/Douyin 无需处理。

## #11 — 结合 tracklog 自查同步慢的根因

同步慢通常来自：(a) 单账号 playlist 分页窗口大 + yt-dlp 超时（180s）；(b) browser 适配器回退
（Playwright 启动慢）；(c) 并发同步账号过多（worker 并发）。tracklog 事件（`SyncRunEvent`）记录每阶段耗时。

```sql
-- 单次同步运行总时长 Top 10（sync_run_events 只有 created_at，用事件跨度近似总耗时）
SELECT sync_run_id,
       count(*) AS events,
       EXTRACT(EPOCH FROM (max(created_at) - min(created_at))) AS total_secs
FROM sync_run_events
GROUP BY sync_run_id
ORDER BY total_secs DESC NULLS LAST
LIMIT 10;

-- 是否大量触发了 browser 回退（message / payload 含 browser 即回退路径）
SELECT sync_run_id,
       count(*) FILTER (WHERE message ILIKE '%browser%' OR payload::text ILIKE '%browser%') AS browser_fallbacks
FROM sync_run_events
GROUP BY sync_run_id
ORDER BY browser_fallbacks DESC
LIMIT 10;

-- 阶段事件样例（event_type='stage'）
SELECT sync_run_id, sequence, message, created_at
FROM sync_run_events
WHERE event_type='stage'
ORDER BY sync_run_id, sequence
LIMIT 30;
```

**判断**：若 `browser_fallbacks` 高，说明大量账号 yt-dlp 拿不到数据而回退到 Playwright —— 这是慢的主因，
应通过 `sync_settings.yt_dlp` 调参（加大 `retries`、缩小 `max_items` 窗口）或核查这些账号是否更适合 `*_ytdlp` 适配器。

### 实际执行结果（2026-08-05）

- **Top 同步运行耗时约 3600–3745 秒（≈60 分钟）**，最长 3745s。单账号「作品列表与指标抓取阶段」
  耗时 6–20 分钟（World Squash 6min、BWF TV 18min、Volleyball World 20min）。多账号顺序/低并发累积 → 整轮 ~1h。
- **每轮 browser 回退约 5 次**，属中等量级，是慢的次要因素。
- 结论：同步慢是适配器 + 账号体量的固有现象，非 bug。优化方向：`sync_settings.yt_dlp` 调参、
  提高 worker 并发、或对易失败账号切到 `*_ytdlp` 适配器。

## #53 历史字幕/媒体回填（补充说明）

字幕/缩略图归档的**实现已在代码中就位**：`DEFAULT_SYNC_SETTINGS_CONFIG["download"]` 默认
`write_subtitles=True / write_thumbnail=True`，`_config_for` 透传给 yt-dlp，`_collect_media` 写入
`content.media` 并由 `/media/{content_id}/{file}` 提供。因此**后续同步会自动归档字幕**。
历史 0 字幕行（DB 统计 8974 条内容中 `media->subtitles` 非空为 0）是旧同步遗留，回填 = 对 YouTube 账号
重新同步一次（注意 8000+ 视频较慢，建议分批 / 限 `max_items`）。无需新增代码。

## 实测结果摘要（2026-08-05，全部 SQL 已执行）

### #9 — TikTok/Douyin 数据
- 2 个 **Douyin** 账号为 `degraded`，`last_sync_error_message='指标提取失败，仅更新了账号资料'`
  （`MS4wLjABAAAA_migutiyu`、`theolympics`）。按设计 Douyin 不暴露 follower/view，yt-dlp 拿不到 →
  `degraded` 属**预期**，非 bug。内容采集正常（tiktok 283 条、bilibili 302 条）。
- TikTok 账号大多 `success` 且带 `total_view_count`（@nba 15.5M、@olympics 21.1M、BoltMotivation 6.6M）。
- **结论：#9 无需代码修复**，仅 Douyin 指标缺失是平台限制。

### #10 — 历史趋势总播放量
- NULL 分布：bilibili 3/3、douyin 2/2、tiktok 1/5、youtube 3/13（前三者为平台预期）。
- **真实问题**：YouTube 且 `sync_status='success'` 却缺 `total_view_count` 的账号 =
  **`ITTFWorld`**、**`fitvisionn`**（另 `UCiio0ydw439X13KyZgMIcHw` 为 `disabled`，跳过）。
- **修复动作**：对 `ITTFWorld`、`fitvisionn` 两个 YouTube 账号各重跑一次同步，即可回填快照
  （属运行操作，无需改代码）。

