# 账号同步完整链路测试报告

日期：2026-08-11

## 结论

前端真实操作链路已通过：登录 → 账号监控 → 选择 TikTok 账号 → 打开同步设置 → 保存并同步 → 观察进度 → 打开账号详情 → 查看作品列表 → 打开作品详情。

目标账号为 `Olympics™`（TikTok，公开账号）。前端显示同步在约 15 秒内完成 `15/15 · 100%`，账号详情可见真实公开指标，作品页显示 `117` 条真实作品，作品详情包含标题、来源 URL、播放、点赞、评论和分享数据。浏览器控制台错误为空。

这次验证只证明公开账号的增量同步链路可用；不把需要官方 API、私有分析权限、登录 Cookie 或验证码的指标伪装成成功。

## 本轮修复

- 同步任务将剩余时间预算传给账号资料、账号指标、作品分页、作品分析和 yt-dlp 子进程；默认 socket timeout 15 秒、重试 3 次、子进程硬上限 90 秒。
- 作品目录使用 flat-playlist 快速路径；详情解析失败时保留真实目录行，不让单条作品拖垮整页。
- TikTok/抖音历史深分页采用 250 条目录窗口，按同步器的 50 条页面切片，并在一次运行内缓存目录，避免每一页重复请求账号列表。
- TikTok 深分页遇到 429 时，在同一个总时间预算内轮换 yt-dlp 的 `app_info` 提取通道；默认内部重试让位给备用通道，避免重复撞同一个限流入口。
- 断点在每页提交后持久化。只要仍有后续 cursor，就显示 `degraded` 并保留 cursor，绝不把未取完的账号标为 `complete`。
- YouTube、TikTok、抖音、Bilibili 浏览器目录适配器均保留 cursor/page slice/dedup 逻辑，避免后续页重复第一页。

## 真实数据验证

目标 TikTok 账号历史回补结果：

- 第一个真实深分页窗口：`250/250`，cursor 从 `400` 推进到 `650`，作品数达到 `649`。
- 部署 429 恢复后再次回补：`250/250`，cursor 从 `650` 推进到 `900`，作品数达到 `899`。
- 单次运行约 58 秒内明确结束，没有卡住；日志显示一次目录枚举 250 条，并完成 5 个 50 条页面。
- 任务仍为 `degraded` 是正确状态：公开账号还有后续 cursor，`content_sync_complete=false`，断点已保留为 `900`。

对照实验确认：容器内直接使用原始 `tiktokuser:<channel_id>` 深分页会收到 HTTP 429；同一命令加入 yt-dlp 支持的 `app_info` 备用通道后可返回 50 条。修复后真实同步已成功从 650 推进到 900。

## 自动化与 Docker 验证

- `docker compose build api worker beat`：通过。
- `docker compose up -d`：通过；api、worker、beat 已更新，postgres、redis、browser、web healthy。
- `docker compose ps`：通过。
- API readiness：`GET /health/ready` 返回 `{"status":"ok","checks":{"database":"ok","redis":"ok"}`。
- 数据库迁移：`20260808_0001 (head)`。
- Ruff：本轮变更文件通过。
- Python compileall：通过。
- `pytest -q tests/test_yt_dlp_adapter.py tests/test_sync_fast_listing.py`：`53 passed`。
- 同步状态/部分入库/卡住保护/进度/登录墙回归：`83 passed`。
- 本轮定向回归合计：`136 passed`，仅有项目已有的 Starlette/httpx 弃用警告。
- 未宣称全仓库 pytest 通过；全量套件此前超过 600 秒未完成，因此不作为本轮验收依据。

## 边界与后续

- “degraded + 保留 cursor”代表平台限流、登录墙或目录仍未结束时的可恢复状态，不代表静默丢失或错误成功。
- 播放、点赞、评论、分享等适配器真实返回的公开字段会展示；完播率、平均观看时长、流量来源、变现等私有分析字段仍明确显示所需 API/登录条件。
- YouTube、TikTok、抖音、Bilibili 的真实表现仍受当前出口 IP、平台限流、Cookie、验证码和账号权限影响；系统不绕过这些安全机制。要让受限账号获得完整历史，应在系统中配置用户合法捕获的登录 Cookie/浏览器会话。
