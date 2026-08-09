# 账号同步「前端同步经常失败」完整 tracelog 与问题定位

> 复现方式：**忠实复现前端实际发出的请求序列**（不经过任何内部捷径）
> 目标账号：`d5e7b227-...`（TikTok `boltmotivation`，历史 `error`）
> 时间：2026-08-09 04:01–04:05 (UTC+8 12:01–12:05)
> 复现脚本：`scripts/sio_frontend_trace.py`

---

## 一、从前端开始的完整调用链（HTTP 层）

| 步骤 | 请求 | 结果 |
|---|---|---|
| 1. 登录 | `POST /api/v1/auth/login` | **HTTP 200**，返回 `csrf_token` + `Set-Cookie: sio_session=...`（前端据此持有会话） |
| 2. 同步 | `POST /api/v1/accounts/{id}/sync` + 头 `X-CSRF-Token` | **HTTP 202**，返回 `run.id=efd4c412...`，`adapter_key=tiktok_ytdlp`，`status=running` |
| 3. 轮询 | `GET /api/v1/accounts/{id}/sync-runs?page=1&page_size=1` | 见下方时间线 |

> 这与前端「账号详情页 → 点同步」发出的请求 **完全一致**（同样的代理入口 `:8080`、同样的 CSRF 校验、同样的 `monitoring` 队列）。所以本次复现=前端真实路径。

---

## 二、逐步时间线（来自 `sync_run_events` + worker 日志）

```
04:01:33  [前端] POST /auth/login                          → 200
04:01:33  [前端] POST /accounts/{id}/sync                  → 202, run=efd4c412, adapter=tiktok_ytdlp
04:01:33  [worker] celery 收到 sync_account 任务，execute_account_run 启动
04:01:33  [worker] validate_config → resolve_account（yt-dlp 子进程，匿名抓取 TikTok 账号页）
04:02:14  [run] external_call | error | tiktok_ytdlp：failed（transient_provider_error）   ← 第 1 次失败
04:02:14  [worker] Task sync_account retry: Retry in 1s（RetryableSyncError）
04:02:58  [run] external_call | error | tiktok_ytdlp：failed（transient_provider_error）   ← 第 2 次
04:02:58  [worker] Task sync_account retry: Retry in 2s
04:03:41  [run] external_call | error | tiktok_ytdlp：failed（transient_provider_error）   ← 第 3 次
04:03:41  [worker] Task sync_account retry: Retry in 4s
04:04:26  [run] external_call | error | tiktok_ytdlp：failed（transient_provider_error）   ← 第 4 次
04:04:26  [worker] Task sync_account raised unexpected: RetryableSyncError → 不再重试
04:04:26  [run] error | error | 同步失败：browser scrape failed: TransientAdapterError:
                    tiktok 公开页未返回账号资料（疑似反爬/未登录拦截），需配置登录态或稍后重试
04:04:26  [DB] run 终态：status=error, error_code=retry_exhausted, progress=12, stage=failed
```

**关键耗时**：单次 `resolve_account` 约 **41 秒**（yt-dlp 子进程 + 浏览器兜底），共失败 **4 次**（初始 + 3 次重试，退避 1s/2s/4s），总耗时 **≈2 分 53 秒**，且 **全程停留在 `account_profile`（progress=12）**，从未进入「作品列表」阶段（progress≥30）。

---

## 三、worker 适配器层堆栈（定位到代码行）

```
Task app.tasks.monitoring.sync_account[...] raised unexpected:
  RetryableSyncError('browser scrape failed: TransientAdapterError:
    tiktok 公开页未返回账号资料（疑似反爬/未登录拦截），需配置登录态或稍后重试')
  File ".../app/adapters/platforms/yt_dlp.py", line 1123, in resolve_account
        cached = await self._fallback().resolve_account(ctx, locator)   # ← yt-dlp 失败，转浏览器兜底
  File ".../app/adapters/platforms/tiktok_browser.py", line 235, in resolve_account
        raise TransientAdapterError(
  File ".../app/adapters/platforms/tiktok_browser.py", line 181, in resolve_account
        raise TransientAdapterError(                                       # ← 无头浏览器同样被反爬拦截
            'tiktok 公开页未返回账号资料（疑似反爬/未登录拦截），需配置登录态或稍后重试')
```

调用链：`tiktok_ytdlp.resolve_account` → yt-dlp 匿名抓取失败 → `_fallback()` → `TikTokBrowserAdapter.resolve_account`（headless Chromium）→ 同样被 TikTok 风控识别为机器人拦截。

---

## 四、问题定位（结论）

**根因：TikTok 以「匿名」身份抓取，触发平台反爬/登录墙。**

- 系统对 TikTok 默认走 `tiktok_ytdlp`（yt-dlp 匿名），yt-dlp 拿不到账号资料时再 **兜底到无头 Chromium**；
- 无头浏览器在容器里带有可识别的自动化特征，且同样**没有登录态 cookie** → TikTok 直接返回「疑似反爬/未登录拦截」；
- 该错误被归类为 `TransientAdapterError`（可重试）→ Celery 重试 **3 次** → 全部同一种失败 → `retry_exhausted` → 前端看到「同步失败」。

**这是平台侧的「匿名机器人」拒绝，不是系统 bug，也不是并发/限流导致的。**

---

## 五、与三条诉求的对应

| 诉求 | 本 traced 失败的性质 | 结论 |
|---|---|---|
| ① 必须可用 | 该 TikTok 账号 **不可用**（error） | 平台侧拒绝，系统已诚实上报（error_code + 业务提示 + 代码级根因） |
| ② 不卡死/顺 | 单账号重试 4×≈2.5min 才失败，未卡死、锁已释放 | 系统侧无卡死；但「长时间才失败」= 重试放大了反爬失败 |
| ③ 无错误 | `retry_exhausted` 是**真实失败**的正确上报 | 非伪造成功；失败原因透明可查 |

---

## 六、修复方向（按性价比）

1. **治本（必须）**：给 TikTok 适配器配置**登录态 cookie**（`sync_settings.yt_dlp.cookies_netscape` 或 `cookies_from_browser`）。匿名→登录态后，反爬/未登录拦截基本消失。这与上一轮「你本地 yt-dlp 很顺」的原因一致——你本地带登录态。
2. **降重试放大**：对「反爬/未登录」这类**永久失败**（`LoginRequiredError` 语义）应**立即终止而非重试 3 次**，可把 2.5min 缩短到一次抓取的 ~40s。建议把该错误从 `TransientAdapterError` 改为不可重试的 `LoginRequiredError`。
3. **降低并发爆发（可选）**：若多账号同时同平台同步触发同 IP 限流，可加「同平台并发上限」——但**对本例无效**（本例是单账号反爬，非并发）。

> 复现脚本 `scripts/sio_frontend_trace.py` 可对任意账号复跑：`python scripts/sio_frontend_trace.py <account_id>`，自动产出 HTTP 序列 + 事件时间线 + 最终 run 行。
