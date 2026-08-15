# 体育情报 OS — 待办与状态文档（交接版）

> 更新时间：2026-08-10 19:22（GMT+8）
> 适用对象：接手后续开发的工程师
> 目的：固化当前系统状态、已完成工作、剩余待办与运维要点，便于无缝交接

---

## 一、系统现状速览

### 1.1 已部署的代码版本（按时间倒序）
| 提交 | 内容 | 状态 |
|------|------|------|
| `2d02765` | fix(tiktok): 已配置登录态时反爬墙改为可重试 | ✅ 已部署（api/worker/beat 三镜像） |
| `b50e3bc` | feat(sync): 从浏览器适配器 metadata 补全作品互动指标 | ✅ 已部署 |
| `c5cd0e4` | feat(semantic): 增量向量索引 + embedding 缓存 | ✅ 已部署 |
| `a5bae87` | docs: 系统后续开发建议书 | ✅ |
| `1bfba0b` | fix(yt_dlp): TikTok 反爬 rehydration 错误恢复 | ✅ |

### 1.2 容器健康（截至 19:22）
全部 `Up` 且关键服务 `healthy`：api / worker / beat（重启约 25 分钟前，即三镜像提交后）、web / postgres / browser / redis。
- 快速验证：`docker compose exec -T api sh -lc "cd /workspace/apps/api && python -c \"import urllib.request;print(urllib.request.urlopen('http://localhost:8000/health/ready').status)\""` → **200**（已现场确认）

### 1.3 关键运维事实
- **源码烘焙进镜像、pypi 不可达** → 改代码 = 本地改 → `docker cp` 进 api/worker/beat → `docker commit` → `up -d --no-build`。**worker/beat 与 api 共用 Dockerfile，adapter/服务层修复必须 api+worker+beat 三处都 cp**。beat 提交须 `--change "HEALTHCHECK NONE"`。
- 容器真实名：`sports-intelligence-os-{api,worker,beat,web,postgres,browser,redis,proxy,llm-experimental}-1`。
- 测试前先清 PG 残留连接防死锁：`docker compose exec -T postgres psql -U sio -d sports_intelligence_test -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='sports_intelligence_test' AND pid<>pg_backend_pid();"`
- 全量 API 测试：`docker compose exec -T api sh -lc "cd /workspace/apps/api && pytest"`（**必须 cd 到 apps/api**，asyncio_mode 配置在那）。CI 顺序 `ruff check → ruff format --check → mypy app`。

---

## 二、已完成工作（详述）

### 2.1 TikTok「已登录仍持续报错」— 已修复并验证 ✅
**根因**（结合 `sync_runs`/`sync_run_events` 日志排查）：凭据其实已正确配置（`platform_credential_settings` 中 tiktok 为 `authorized_session`：32 cookie + `storage_state_json` 均 configured，`session_expires_at=2026-08-17`，CDP `browser:9222`）。cookie 经 `PlatformCredentialService.resolve()` 解密后注入浏览器上下文，**cookie 是生效的**。
决定性证据：同一账号（Olympics™）既有成功抓取 65+ 作品，也有 `login_required` 失败 → 是 **TikTok 对登录态浏览器间歇投放反爬墙**，非缺凭证。

**修复**（`app/adapters/platforms/tiktok_browser.py`）：新增 `_session_configured` / `_raise_login_wall`——仅当 ctx 含 `storage_state_json`/`cookies_netscape` 时，把反爬墙判为 `TransientAdapterError`（retryable），接入既有 `platform_request_max_attempts` 退避自愈；匿名访问仍保持永久失败。覆盖 `resolve_account` 与 `fetch_content_analytics` 两处抛出点。新增 `test_tiktok_login_wall.py`（3 passed）。

**部署后验证（本交接前复核）**：修复后近 2 小时 `tiktok_ytdlp` 运行 **0 错误**（2 degraded + 1 success）；修复前 24h 为 22 失败 / 71% 失败率。`login_required` 永久错误已消失。

**运营侧仍建议**（代码改不了）：换住宅代理、缩短 cookie 重捕获周期、降低并发。

### 2.2 补全适配器互动/评论数据 — 已部署 ✅
**纠偏**：上轮误判 yt_dlp 缺字段，实际它早已读 `view/like/comment/repost`。**真正缺口在同步合成路径**——浏览器适配器列举时已把互动数据写入 `ContentItem.metadata_json`，但同步只取 `view_count/play_count`，like/comment/share 被丢弃。

**修复**（`services/sync.py` + `adapters/platforms/base.py`）：
- 删 `_view_count_from_metadata`，新增 `_metrics_from_metadata`：归一化 `digg→like`、`play/view_text→view`、`repost→share`、`favorite→favorite`、comment 直取；对**任意非空互动指标**生成 `ContentSnapshot`（不再仅限 view_count）。抖音/B站现可落真实 like/comment/share。
- `parse_compact_count` 新增中文 `万/亿/万亿` 后缀（抖音/B站 UI 惯用；此前 `"1.2万"` 误解析为 1）。
- 新增 `test_metrics_from_metadata.py`（12 passed）。

### 2.3 增量向量索引 + embedding 缓存 — 已部署 ✅
见 `c5cd0e4`（#63）。LRU 缓存键 `sha256(model\0text)`，批内去重；`_upsert_content` 返回 4 元组（末位 `indexable_changed`）；启用语义检索时派发 `index_content_item.delay`。新增 `test_embedding_cache.py` + `test_incremental_index_dispatch.py`。

### 2.4 更早完成（参考）
- 同步专项 #65/#66/#76、语义检索 pgvector 落地（详见 `.workbuddy/memory/MEMORY.md`）。
- `docs/系统后续开发建议书.md`：同步实测对比 + 后续优先级。

---

## 三、待办任务清单（按优先级）

### 🔴 P0：`#55` 订阅告警（**唯一真正未启动的 P0**）
- **现状**：后端**无** subscription/alert/notify 端点（grep 仅 incidental 命中）。其余 P0（#57/#58/#61/#62）后端+前端其实已实现，仅缺测试。
- **范围**：订阅规则 CRUD（平台/账号/关键词/阈值）、触发判定（新内容/互动突变/关键词命中）、通知通道（站内/邮件/Webhook）、调度（Celery beat 已有）。
- **建议落点**：`app/models/subscription*.py` + `app/api/routes/subscriptions.py` + `app/services/subscriptions.py` + `tasks/`；复用现有 `monitoring`/`content_snapshots` 数据。
- **验收**：订阅某账号新作品 → 触发通知；端到端测试覆盖规则与触发。

### 🟠 P1：`#57/#58/#61/#62` 已实现端点**补齐测试**（最高性价比）
- **现状**：趋势时间线(#57)、跨平台聚类(#58)、互动快照(#61)、评论挖掘(#62) 的**后端端点+前端均已存在**，但 `tests/` 下**零测试**，前端接线完整性未核实。
- **范围**：为 `GET /contents/{id}/snapshots`、`/metrics`、`/comments`、`POST /comments/collect`、`/trends`、`run_cross_platform_clustering` 补契约/集成测试；核实前端 `trend-chart.tsx`/`derivatives-panel.tsx`/`account-compare-client.tsx` 接线。
- **依赖**：本批次的互动指标补全(#61/#62 数据已不再稀疏)使测试更有意义。

### 🟠 P1：语义检索正式上线（三步走）
1. 部署真实 embedding 后端（TEI/BGE-M3）后跑 `backfill_content_embeddings` 灌 9082 条向量；
2. 存量字幕补齐（`scripts/backfill_subtitles.py` 或 YouTube 重同步）→ 语义检索质量跳档；
3. 前端语义搜索 tab（目前后端已 live，前端未接）。
- 配置：`core/config.py` 的 `SemanticSearchSettings`（`semantic_search_enabled=False, embedding_backend="none"` 默认关）。

### 🟡 P2：`#59` 竞品对比看板 / `#60` 团队共享·收藏·开放 API
- 大体量产品功能，待 P0/P1 完成后排期。

### 🔵 进行中：`#53` 合并结果区自动摘要 + 热度/情感评分
- 状态：in_progress（早期标记，细节待接手人确认当前进度）。

---

## 四、已知问题 / 风险 / 运营建议
1. **TikTok 偶发墙**：已改为可重试，但平台风控可能仍偶发；若失败率回升，优先运营侧（住宅代理/缩短 cookie 周期/降并发）。
2. **已实现功能前端接线未核实**：#57/#58/#61/#62 前端是否完整可用未经验证，接手后应实测。
3. **mypy 35 个 pre-existing error**（`news.py`/`tasks/monitoring.py`/`media.py:203` 等），均非本批次改动文件；本批次 4 文件零新增 error。
4. **YouTube 注册/登录困难**：**无需官方 API OAuth**——系统已支持 `authorized_session`（浏览器 cookie/CDP）模式，与 TikTok 同通道。用老账号经 `browser:9222` CDP 捕获 cookie 即可。
5. **字幕数据现状**：`content_items` 9082 条，存量 `media->subtitles` 全空；仅 yt_dlp(YouTube) 产字幕，browser 适配器只抓元数据。

---

## 五、关键架构与运维要点（接手人必读）
- **适配器映射**（常规同步只用这些 key）：`tiktok → tiktok_ytdlp`、`youtube → youtube_ytdlp`、`douyin → douyin_ytdlp`、`bilibili → bilibili_browser`（见 `platform_catalog_seed.py`）。`tiktok`/`tiktok_browser` 运行来自会话捕获诊断，非常规同步。
- **凭据通道**：`authorized_session` 模式 = 32 cookie + `storage_state_json` + CDP `browser:9222`；`PlatformCredentialService.resolve()` 解密后注入 `browser_base._new_context`。
- **语义检索链路**：查询 → 本地 embedding 服务 → pgvector 余弦 `<=>` → 关键词召回 RRF 融合（不调 LLM，除非总结命中）。
- **跨平台一致性**：账号层改动须覆盖 4 平台 × 2 适配器 = 8 文件（见 MEMORY.md）。
- **完整运维/踩坑细节**：见 `.workbuddy/memory/MEMORY.md` 与 `2026-08-10.md`。

---

## 六、交接检查清单（接手人第一步）
- [ ] `git log --oneline -8` 确认三个部署提交（`2d02765`/`b50e3bc`/`c5cd0e4`）在主线。
- [ ] `docker ps` 确认 api/worker/beat/web/postgres/browser 均 Up/healthy。
- [ ] 跑 `health/ready` 返回 200。
- [ ] 容器内 `pytest tests/test_tiktok_login_wall.py tests/test_metrics_from_metadata.py` 全绿。
- [ ] 打开前端，实测 #57/#58/#61/#62 四个功能的前端接线是否完整。
- [ ] 与用户确认 `#53` 当前进度与 `#55` 启动优先级。
- [ ] （可选）观察 TikTok 同步失败率是否持续低位（验证 2d02765 长期有效）。
