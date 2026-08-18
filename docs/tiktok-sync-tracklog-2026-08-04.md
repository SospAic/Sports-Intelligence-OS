# TikTok 账号同步根因排查 + 完整 Tracklog

**账号**：`@olympicsbringsustogether`
**账号 ID**：`91518412-8113-4e17-aa70-2079840ada7d`
**平台**：tiktok（`platform_id = 288ee49a-9069-591d-a04c-40fe8571860a`）
**工作区**：`a610c7d5-353d-4885-bfdb-43db337bf666`
**同步方式**：通过前端真实路径（`POST /api/v1/accounts/{id}/sync` → Celery worker → `tiktok_ytdlp` 适配器）
**同步时间**：2026-08-04 06:59:58Z → 07:02:43Z（约 166 秒）

---

## 一、根因结论（为什么“始终修不好”）

`content_items` 表的**唯一约束**原先是：

```sql
UNIQUE (workspace_id, platform_id, external_id)   -- 缺 account_id
```

同一工作区、同一平台下，**一个视频只被允许归属一个账号**。当同一视频被多个被监控账号同时收录时（例如 `@olympics` 与 `@olympicsbringsustogether` 都发布了相同的奥运剪辑），第二个账号同步时：

1. `_upsert_content` 按 `(workspace_id, platform_id, external_id)` 查重 → 命中**第一个账号**已存在的那一行；
2. `skip_existing`（默认 True）→ 直接跳过，标记 `skipped`；
3. 28/28 条视频全部被判定为“已存在” → 该账号 `records_created = 0`；
4. 但同步整体 `status = success`，账号作品页显示 **0 条视频**。

这就是“假成功（hollow success）”：系统报告成功，账号却始终空着，看起来“永远修不好”。

**修复**：把 `account_id` 纳入唯一约束与查重条件，让每个账号拥有自己的视频副本。

| 改动文件 | 内容 |
|---|---|
| `apps/api/app/models/monitoring.py` | `UniqueConstraint("workspace_id","platform_id","account_id","external_id")` |
| `apps/api/app/services/sync.py` (`_upsert_content`) | 查重增加 `ContentItem.account_id == account.id` |
| `apps/api/alembic/versions/20260804_0001_content_per_account.py` | 迁移：drop 旧约束 `uq_content_items_workspace_id`，新建 `uq_content_items_account` |

迁移已应用（`alembic current` = `20260804_0001 (head)`）。

---

## 二、修复前 / 修复后 对比

| 指标 | 修复前（同账号上次同步） | 修复后（本次前端同步） |
|---|---|---|
| `status` | success | success |
| `records_created` | 0 | 29 |
| `records_updated` | 1 | 1 |
| `skipped_existing` | **27** | **0** |
| `items_processed / items_total` | 28 / 28 | 28 / 28 |
| 账号实际拥有视频数（DB） | **0** | **28** |

---

## 三、完整同步详细日志（Tracklog）

### 3.1 前端触发的 HTTP 路径（与浏览器“同步”按钮一致）

```
1) POST /api/v1/auth/login
   body: { email, password }
   → Set-Cookie: sio_session=... ; 返回 csrf_token

2) POST /api/v1/accounts/91518412-.../sync
   headers: X-CSRF-Token: <csrf> , X-Workspace-Id: a610c7d5-...
   → 202, 返回 SyncRun（created=true，并 enqueue Celery 任务）

3) GET /api/v1/accounts/91518412-.../sync-runs?page_size=5
   → 轮询直到 terminal 状态（约 170 秒后 success）
```

### 3.2 最终 SyncRun 记录（权威结构化 tracklog）

```json
{
  "id": "1e2d7c38-b6cf-4d2b-8685-0f3b8bbdd247",
  "workspace_id": "a610c7d5-353d-4885-bfdb-43db337bf666",
  "target_type": "account",
  "target_id": "91518412-8113-4e17-aa70-2079840ada7d",
  "adapter_key": "tiktok_ytdlp",
  "queued_at": "2026-08-04T06:59:58.054319Z",
  "started_at": "2026-08-04T06:59:58.244912Z",
  "finished_at": "2026-08-04T07:02:43.943755Z",
  "status": "success",
  "records_created": 29,
  "records_updated": 1,
  "progress_percent": 100,
  "progress_stage": "completed",
  "progress_message": "同步完成",
  "items_processed": 28,
  "items_total": 28,
  "error_code": null,
  "error_message": null,
  "metadata": {
    "trigger": "manual",
    "retry_count": 0,
    "heartbeat_at": "2026-08-04T07:02:43.899999+00:00",
    "skipped_existing": 0
  }
}
```

### 3.3 Worker（Celery）运行日志（本次 run）

```
[06:59:58] Task app.tasks.monitoring.sync_account[71e12f8a-...] received
[07:00:05] yt_dlp account extraction failed for tiktok/olympicsbringsustogether; using browser fallback
[07:02:44] Task app.tasks.monitoring.sync_account[71e12f8a-...] succeeded in 165.88051045500015s: None
```

> 说明：`tiktok_ytdlp` 适配器在抓取账号资料时首选 yt-dlp，对其公开页资料解析失败时自动回退到无头浏览器（符合“浏览器优先兜底”策略），作品列表与指标抓取不受影响，最终成功。

### 3.4 数据库核验（账号真正拥有自己的视频）

```sql
SELECT count(*) FROM content_items
WHERE account_id = '91518412-8113-4e17-aa70-2079840ada7d';
-- = 28  （修复前 = 0）
```

抽样 `canonical_url` 末尾均为本账号专属路径（证明归属正确，不再是 `@olympics` 抢注）：

```
...ingsustogether/video/7665716279348694285
...ingsustogether/video/7662394429017230606
...ingsustogether/video/7661517584411430157
...ingsustogether/video/7660712319827135758
...ingsustogether/video/7659403255767698701
```

账号指标快照保持真实：`video_count = 201`，`follower_count = 61600`。

---

## 四、结论

- **错误根源**：`content_items` 唯一约束 / 查重缺少 `account_id`，导致跨账号共享视频被首个账号“抢注”，后续账号同步全部 `skip_existing` → 假成功、作品页恒为 0。
- **已修复并验证**：重建 api/worker 镜像应用迁移后，通过前端真实路径触发同步，账号现已拥有 **28** 条自己的视频，`skipped_existing` 由 27 降为 0。
- 本次同步为一次性修复验证；此后该账号及任何共享视频的账号，均可在前端正常同步、各自持有作品副本。
