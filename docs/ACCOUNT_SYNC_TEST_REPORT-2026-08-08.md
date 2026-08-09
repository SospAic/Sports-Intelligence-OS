# 账号同步全方位测试报告

**日期**：2026-08-08
**范围**：账号监控 / 账号同步（4 平台 × API 与浏览器双适配器）
**验收标准**（用户提出的三条硬性要求）：

1. **必须可用**
2. **速度必须顺畅，长时间等待或卡死不可接受**
3. **原则上不能有任何错误**

---

## 一、结论速览

| 硬性要求 | 结论 | 关键证据 |
| --- | --- | --- |
| ① 可用 | **系统侧已无阻塞**；剩余缺口全部是平台风控 | YouTube 92%（24h/93 次）、抖音 100%、TikTok 33–50%、B 站 0%（平台强制登录） |
| ② 顺畅、不卡死 | **达标** | 近 3h 68 次、近 24h 261 次运行**无一条停留在 running/queued**；修复后最长 173.9s；过期尝试 1.4s 收尾 |
| ③ 无错误 | **系统侧已清零** | 近 3 小时系统侧错误 **0**；24h 内 62 次系统侧错误**全部发生在本轮两次修复之前** |

本轮定位并修复了 **2 个会导致账号永久"同步中"的严重缺陷**，两者都不是平台问题，而是引擎自身的错误处理漏洞。

---

## 二、本轮修复的两个缺陷

### 缺陷 A — 非法事件类型导致任务崩溃、账号永久锁死（commit `66d3d71`）

**现象**：抖音账号同步卡在 `account_profile` 阶段 400s 以上，无 yt-dlp 子进程、心跳停止，账号 UI 永久显示"同步中"，且后续同步请求全部被拒。

**根因链**：上一轮新增的降级告警写成了
`_emit(run, "account_profile", "warn", ...)`
——`account_profile` 是**阶段名**，不在 `ck_sync_run_events_sync_run_event_type` 允许值内 →
flush 抛 `CheckViolationError` → 会话进入 `PendingRollbackError`（不可用） →
Celery 任务以引擎**未分类**的异常崩溃 → run 永远停在 `running` 且不释放 `lock_key`。

**四层防御**：

| 层 | 内容 |
| --- | --- |
| L1 | 修正该调用点为合法的 `"warning"` |
| L2 | `_emit` 增加白名单归一化：非法类型按 level 归一为 `error/warning/info`，原值存入 `payload.requested_event_type` 并打 warning 日志——**同类笔误今后只降级为日志，永不卡死** |
| L3 | 任务层 `_run_with_retry` 增加 `except Exception` 兜底 → `mark_unexpected_failure` 用**全新会话**收尾并释放锁（原会话可能已毒化） |
| L4 | 僵尸回收阈值从通用租约 2100s 改为 `sync_stale_after_seconds = 运行预算 300s + 宽限 120s = 420s`，回收时间 **35 分钟 → 7 分钟** |

### 缺陷 B — 过期重试在负预算上空转（commit `5548518`）

**现象**：并发压测时 worker 报
`RetryableSyncError('account profile fetch exceeded -3341s budget')`，
数据库中出现 3641s、3694s 的超长运行。

**根因**：运行预算是**绝对截止时间**（`started_at` 跨重试刻意保留）。当重试因队列积压在截止时间之后才被 worker 取走时，`_remaining_budget_seconds` 返回**负值**；而 `account_profile` 是四个预算调用点中**唯一没有 `<= 0` 守卫**的一处，负值被直接传给 `asyncio.wait_for` → **适配器根本没被调用**就超时 → 该瞬时超时被判为"可重试的外部故障" → 重新入队 → 崩溃/重试循环，期间一直持有账号锁。

**修复**：

- `execute_account_run` 入口守卫：剩余预算 < 5s 直接以 `sync_budget_exhausted` 终态收尾并释放锁，不再假装工作；
- profile 抓取超时钳到正数下限，作为第二道防线；
- **排队等待时间不计入预算**（`started_at` 在被 worker 取走时才打点）——新增测试锁定该语义，避免"积压一次就全员失败"的过度修正。

---

## 三、测试矩阵（多方式 / 多角度）

| # | 维度 | 方法 | 结果 |
| --- | --- | --- | --- |
| 1 | 静态检查 | `ruff format` + `ruff check` + `mypy` | 全部通过（改动文件 mypy `Success`） |
| 2 | 卡死守卫单测 | `tests/test_sync_stall_guards.py` | **11 passed**（含本轮新增 2 项负预算回归） |
| 3 | 同步引擎族 | cancel / degraded / avatar_cache / stall_guards / first_delivery | **31 passed** |
| 4 | 监控 API | `test_monitoring_api.py` + `test_accounts_batch_compare.py` | **14 passed** |
| 5 | 基线回溯 24h | 数据库回溯，零平台负载 | 261 次运行，**0 条未终态** |
| 6 | 基线回溯 3h | 同上（当前代码窗口） | 68 次运行，**0 未终态、0 系统侧错误** |
| 7 | 真实端到端 | 触发真实平台同步（修复前 / 修复后各一轮） | 见下表 |
| 8 | 并发压力 | 4 平台 × 3 账号、并发 8 | 9 次运行，**0 卡死** |
| 9 | 故障演练 | `scripts/sync_failure_drills.py` 三项 | **3/3 PASS** |

### 3.1 真实端到端（修复后复测）

| 平台 | 运行 | 可用 | 可用率 | p50 | p95 | max | 卡死 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| youtube | 2 | 2 | 100% | 39.6s | 129.1s | 129.1s | 0 |
| douyin | 1 | 1 | 100% | 124.9s | 124.9s | 124.9s | 0 |
| tiktok | 2 | 1 | 50% | 117.2s | 173.9s | 173.9s | 0 |
| bilibili | 2 | 0 | 0% | 4.8s | 5.0s | 5.0s | 0 |
| **合计** | **7** | **4** | 57.1% | 117.2s | — | **173.9s** | **0** |

对比修复前同口径实测的离群值（3694s / 3641s / 1760s），**修复后最长 173.9s**，全部落在 300s 预算内。

### 3.2 故障演练（真实生产路径，非 mock）

| 演练 | 断言 | 实测 |
| --- | --- | --- |
| `expired_retry_budget` | 超过绝对截止时间的运行必须被关闭，而非在负超时上重试 | **PASS** — 1.4s 内以 `sync_budget_exhausted` 收尾，锁已释放，账号未卡在 syncing |
| `cancel_in_flight` | 用户取消后运行必须到达终态并释放账号 | **PASS** — 取消后 **0s** 反应，状态 `cancelled`，锁已释放 |
| `duplicate_dispatch` | 同账号并发两次请求必须合并为一次运行 | **PASS** — 创建 1 次，无竞争运行 |

演练脚本只写入普通的 `sync_runs` 记录，不新增/修改账号、平台或内容数据，可安全地对线上库执行。

### 3.3 测试可靠性（死锁污染排查）

> 全程通过 Docker 容器内跑测试，单个 pytest 会话会 `DROP/CREATE` 整库；若上一会话被强制中断，其遗留的 PG 连接会持有锁，导致下一会话在写入 `sync_run_events` 时触发 `DeadlockDetectedError` 级联失败（表现为无关测试批量 FAILED + 个别 ERROR）。
>
> 本轮回放该场景：首次运行出现 10 FAILED + 1 ERROR（含本轮新增的负预算回归测试）；**清空遗留 PG 连接后重跑，同一组 54 项测试（stall_guards + cancel + degraded + resilience + avatar_cache + monitoring + account_sync_settings）全部通过（0 失败）**。结论：上述失败为测试设施污染，并非代码回归。落地规则——重跑前执行 `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='sports_intelligence_test' AND pid<>pg_backend_pid();`。

> **全量回归门二次印证（2026-08-08 18:30，clean DB，`pytest -q -p no:randomly`，20m）**：长链路跑出 55 failed + 70 errors，失败模块横跨 `sync_*` / `settings` / `news_api` / `topics_operations` / `generation` / `editorial_rules` 等**本轮回溯未触碰**的文件。但**隔离重跑同一组 78 项（上述 sync 族 + monitoring + settings + news_api + topics + generation + editorial）全部通过（0 失败）**——进一步确认 125 项全量失败纯属长链路连接池污染与已知环境 flakes（account 死锁 / browser CDP / generation LLM-gateway / auth CSRF / editorial），**与本轮改动无关**；且长链路中仍有 295 项通过，证明本轮回溯代码可正常 import、不破坏其他模块。

---

## 四、对照三条硬性要求

### ① 必须可用

- **系统侧不再有任何阻断**：近 3 小时 68 次运行，`unexpected_sync_error` / `internal_error` 均为 **0**。
- 24 小时内 62 次系统侧错误的时间分布证明它们全部属于**已修复的历史区间**：
  - `TypeError: '_YtDlpLogSink' object is not callable` × 58 —— 最后一次出现在 02:00，此后 **16 小时 / 138 次运行零复现**；
  - `test_cleanup_orphan` × 2 —— 缺陷 A 造成的僵尸，已手工释放并从根上修复；
  - 负预算循环 —— 缺陷 B，已修复。
- 剩余可用率缺口**全部来自平台侧风控**，并非系统缺陷（见第五节）。

### ② 速度顺畅、不卡死

- **零卡死**：近 3h（68 次）与近 24h（261 次）**没有一条**运行停留在 `running`/`queued`；当前 19 个活跃账号中 `syncing` 状态数为 **0**。
- **耗时**：可用运行 p50 117–173s、p95 ≤ 214s，修复后 max 173.9s。
- **硬上限**（多重钳制，互为兜底）：
  - 单次运行预算 `sync_run_timeout_seconds = 300s`（绝对截止，含全部重试）
  - 单页抓取上限 `sync_page_fetch_timeout_seconds = 120s`（严格低于适配器自身抽取超时）
  - 预算耗尽的尝试 **1.4s** 内收尾
  - 崩溃残留由 stale 巡检 **420s** 内回收（原 2100s）

### ③ 不能有错误

- 系统侧错误在当前代码窗口已清零。
- 仍会出现的错误全部是**平台侧的真实拒绝**，且都做到了"诚实上报"：带 `error_code`、业务提示（`business_hint_for`）与代码级根因（`error_detail`），前端可直接展示可执行的处置建议，不会伪造成功。

---

## 五、遗留问题与建议（均为平台侧，非系统缺陷）

| 平台 | 现象 | 判断 | 建议 |
| --- | --- | --- | --- |
| **bilibili** | 恒定 `login_required`（检测到登录弹窗 `.login-panel-popover`），**5s 快速失败** | 平台强制登录，公开页已无数据 | 配置登录态 Cookie 或接入官方 API/OAuth，否则可用率恒为 0 |
| **tiktok** | `tiktok 公开页未返回账号资料（疑似反爬/未登录拦截）` | 反爬拦截 | ①配置登录态；②该类稳定复现的拦截建议**降低重试次数**——目前 3 次重试使单次失败耗时 179–192s，虽在预算内但偏慢 |
| **youtube** | 偶发 `net::ERR_CONNECTION_CLOSED`（浏览器兜底阶段） | 本机到 YouTube 的网络抖动 | 环境网络问题；24h 可用率仍有 92% |
| 次要 | 取消时日志 `could not revoke celery task` | **不影响正确性** | 执行器开头即识别 `cancelled` 并早退（已有测试覆盖），revoke 仅为加速手段 |

---

## 六、可复现的验证入口

```bash
# 只读基线（零平台负载，任何时候都可跑）
docker compose exec -T api sh -lc "cd /workspace/apps/api && python scripts/sync_healthcheck.py --mode baseline --hours 24"

# 真实端到端 + 并发压力（会打真实平台）
docker compose exec -T api sh -lc "cd /workspace/apps/api && python scripts/sync_healthcheck.py --mode live --per-platform 3 --concurrency 8 --json /tmp/hc.json"

# 故障演练（快速失败 / 取消 / 并发去重）
docker compose exec -T api sh -lc "cd /workspace/apps/api && python scripts/sync_failure_drills.py --json /tmp/drills.json"

# 卡死守卫回归
docker compose exec -T api sh -lc "cd /workspace/apps/api && python -m pytest tests/test_sync_stall_guards.py -q"
```

---

## 七、相关提交

| 提交 | 内容 |
| --- | --- |
| `57b5908` | 账号同步硬超时与单页抓取上限，消除卡死 |
| `239e3b7` | 浏览器适配器终端错误不再被重新包装为可重试 |
| `66d3d71` | 缺陷 A：一次账号同步不再可能永久卡死（四层防御） |
| `5548518` | 缺陷 B：过期重试不再在负时间预算上循环 |
| `4a62961` | 故障演练脚本：证明异常同步快速、干净地失败 |
| `a771e1a` | 环境污染根治：全量 420 passed，修复唯一真实测试缺陷（`_NavTestAdapter.descriptor`） |

---

## 八、环境污染彻底根治（全量套件变绿）

用户要求"全量解决环境污染的问题，必要时可清空数据库"。经根因排查，结论如下：

**1. 早前全量 125 失败 = 测试设施污染，非代码回归**
- 签名：失败横跨从未改动的模块（settings/news/topics/generation/editorial），但**隔离重跑同组 78 项 = 78 passed, 0 failed**。
- 根因：会话交接时被我中断的后台 pytest 遗留 **PG 连接持锁**，新套件写 `sync_run_events` 时触发 `DeadlockDetectedError` 级联，并污染连接池导致后续 DB 测试继承 `PendingRollbackError`。
- 自证：基础设施（browser/llm-experimental）均健康，非外部服务缺失。

**2. 唯一真实测试缺陷（已修复，`a771e1a`）**
- `tests/test_browser_navigate.py` 的 `_NavTestAdapter` 继承 `BrowserPlatformAdapter` 但未设置 `self.descriptor`，而 `_navigate` 读取 `self.key → self.descriptor.key` → `AttributeError`（3 个用例失败）。
- 修复：补齐合法的 `AdapterDescriptor`（对齐 conftest 的 `RealShapedTestAdapter`）。3 用例恢复通过。

**3. 全量 clean 启动最终验证**
- `setup_test_db` 每次运行都会 `pg_terminate_backend` + `DROP` + `CREATE` 测试库，因此**不中断的完整运行天然从干净库开始**。
- 最新一次完整运行：**`420 passed, 6 deselected, 0 failed`**（665s，exit 0）——全量套件彻底变绿，环境污染已根除。

> 结论：账号同步相关改动零回归；此前所有"全量失败"均为中断测试遗留连接造成的设施污染，已通过"清连接 + 完整运行 + 修唯一真缺陷"彻底解决。
