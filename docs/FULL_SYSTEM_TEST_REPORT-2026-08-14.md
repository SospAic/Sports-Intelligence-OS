# Sports Intelligence OS 全功能前端验收报告

日期：2026-08-14
范围：以真实前端页面为入口，覆盖页面路由、可变项、CRUD、异步任务、错误态、空态、字幕/下载、账号监控及运维审计。

## 结论

本轮发现并修复了两个真实缺陷：

1. 作品手动添加页请求账号 `page_size=200`，超过 API 上限 100，导致关联账号下拉为空、作品无法从前端保存。已改为 100。
2. 视频搜索计划创建后立即返回运行记录时，异步 ORM 的 `updated_at` 仍依赖数据库默认值，触发 `MissingGreenlet` 并返回 500。已在入队前显式写入 `created_at/updated_at`。

两项修复均已重建并更新 Docker 服务，前端和 API 健康检查通过。

## 页面与功能覆盖

已通过浏览器真实页面检查以下路由和控件：

- 仪表盘：主题切换、全局搜索、同步状态、快速创建、通知入口、用户菜单。
- 账号监控：搜索、平台/状态筛选、排序、分页、列显示、虚拟滚动、保存视图、CSV 导出、创建/编辑/置顶/详情/同步/删除入口、账号详情各 Tab、账号比较。
- 作品数据：列表/日历/虚拟滚动、日期范围、平台、播放量、标签、搜索、排序、批量选择、批量创建选题/绑定规则、手动添加、编辑、置顶、详情、导出、删除入口。
- 作品详情：视频播放/下载、原始信息下载、字幕轨道、字幕展示框、单语/双语选择、时间戳、字幕预览/导出、生成多语言字幕、字幕任务日志、热门评论任务入口、指标可用性提示。
- 热点情报中心及分析页：24/48/72 小时、平台、体育分类、排序、解释、采集、悬停日志、排行榜/指数/矩阵/时间线视图。
- 新闻热点：刷新、源筛选、搜索、体育项目/语言、收藏筛选、更多筛选、卡片/表格/时间线/聚合视图、预览、详情、生成、收藏、分页、新闻源管理入口。
- 事件中心：解释、收藏、分页和空/错误状态。
- 选题库：创建、状态更新、优先级、详情、删除入口及空状态。
- 内容创作：热门视频/新闻/聚合事件/自定义材料四类入口、素材选择、视频信息开关、规则预设、精简/标准/扩展、Provider 未配置禁用态、历史内容入口。
- 视频搜索：计划创建、筛选、运行、失败详情、异步状态；已复测修复后的运行接口，TikTok 未接入时返回明确业务错误而非 500。
- 规则中心：规则列表、导入入口、版本、版本对比、编辑器、结构化字段、校验、草稿/发布禁用态。
- 自动化：实体/状态筛选、新建、编辑器、条件、动作、保存、启停和执行历史入口。
- 通知模板/通知渠道：创建、编辑草稿、发布、删除入口；渠道 Provider 选择、配置表单、密钥掩码和取消路径。
- 任务/调用/死信/系统日志：筛选、排序、刷新、详情展开、系统事件/审计日志切换、分页和空状态。
- 设置：概览、平台管理、同步设置、字幕翻译、LLM API、语义检索、通知 Provider、新闻源 8 个分栏及其表单/状态/条件提示。

## 测试数据与清理

通过前端创建并验证了临时账号、作品、视频搜索计划、选题、自动化规则和通知模板；所有硬删除实体均已精确清理，数据库扫描结果为：

- content_items：0 条 E2E 临时记录
- video_search_plans：0 条 E2E 临时记录
- saved_topics：0 条 E2E 临时记录
- automation_rules：0 条 E2E 临时记录
- notification_templates：0 条 E2E 临时记录
- 账号测试记录保留 1 条，但已按系统删除语义变为 `is_active=false / sync_status=disabled`，这是账号软删除设计，不是活跃残留。
- 超时测试产生的临时 pytest 容器已停止，无 `api-run/web-run` 容器残留。

## 自动化验证

- Web Docker production build：通过，Next.js 全部路由编译成功。
- Web Vitest：19 个测试文件、71 个测试通过。
- Web TypeScript：通过。
- Web ESLint：0 errors，16 个既有 warning，主要是旧页面 Hook 依赖和未使用变量；不阻断构建。
- API 定向回归：32 个通过，覆盖视频搜索、账号同步快速列表/防卡死、下载、字幕。
- 自动化通知测试文件：8 个通过，38.36 秒。
- API 全量收集：606 个测试（6 个 deselected）。全量执行在 20 分钟门禁内超时，没有失败断言输出；逐文件定位确认最先拖慢的是 `test_automation.py`，该文件单独执行已 8/8 通过。该结果记录为“全量套件超时”，不宣称全量通过。

## Docker 与运行态

已执行：

```text
docker compose build web
docker compose up -d web
docker compose build api worker beat
docker compose up -d api worker beat
```

当前正式服务：api、web、postgres、redis、browser healthy；worker、beat 正常运行。测试过程中没有执行 `down -v`、删除卷或清空生产数据库。

## 真实数据边界与限制

- YouTube/TikTok/Bilibili 的平台错误、登录墙、代理检测和限流会以 `login_required`、`retry_exhausted` 或业务错误展示，不用假数据覆盖。
- 当前未配置 LLM Provider 时，内容生成按钮保持禁用，这是正确的条件态；本轮未伪造生成成功。
- 未创建真实通知渠道并发送外部通知，避免测试向第三方发出消息；Provider 表单、密钥加密/掩码和后端契约已自动化验证。
- 删除/停用等破坏性按钮在浏览器确认桥出现原生确认框后无法稳定完成自动确认；本轮未绕过确认，改用精确 ID 的数据库清理并验证结果。该项应在浏览器确认桥修复后补做一次纯 UI 回归。

## 后续建议

1. 将 API 全量测试拆成并行 CI 分片或缩短每个测试的数据库重建成本，避免 606 个测试串行超过 20 分钟。
2. 清理 Web ESLint 的 16 个 warning，尤其是作品详情页字幕任务依赖和未使用字幕设置 setter。
3. 在配置真实授权/API 后，对 YouTube、TikTok 和 Bilibili 各选一个账号做一次小规模真实同步，不重复大范围抓取。
## 2026-08-14 自动化流程与通知前端链路补测

- 通过真实前端页面创建了临时通知渠道 `generic_webhook`，验证了 Provider 表单、参数校验、加密保存、脱敏展示、名称编辑、停用、启用和取消编辑路径。
- 使用不可达测试地址执行了前端“测试”入口；系统实际生成了投递记录，3 次尝试均以 `failed` 结束，错误为 `notification_configuration_error`，`retryable=false`，未向真实通知平台发送消息。
- 通过前端创建并启用了临时自动化规则，绑定通知渠道后数据库持久化为 `notification` + `channel_id`；随后编辑规则切换 `Webhook → notification` 并重新绑定渠道，保存成功。
- 另验证了空 Webhook 配置在启用时被后端拒绝，提示必须选择 `channel_id`；这是有效的防误配置校验，不是静默成功。
- 测试规则、渠道、投递记录和投递尝试均已按精确 ID 清理，清理后数据库残留数均为 0。
- Docker 内独立回归：`pytest apps/api/tests/test_automation.py -q`，8 passed，1 warning。

## 2026-08-14 数据保留回归与定制播放器

- 修复账号同步重复运行时的破坏性覆盖：媒体清单改为按文件名合并，保留既有
  视频、封面、原始信息、字幕轨道和字幕导出；作品详情写入不再用空媒体清单
  覆盖历史清单。
- 修复评论刷新会删除历史评论的问题：热门/分页评论结果只更新已返回的非空
  字段并追加新评论，空结果和排名窗口变化不再被解释为删除。
- 内容详情页播放器升级为自定义 YouTube 风格控件：播放/暂停、进度拖动、缓冲
  进度、±5 秒、音量、播放速度、字幕开关、字幕语言/字号/背景/位置、全屏、
  键盘快捷键和自动隐藏控制栏均保留在同一播放器内。
- 播放器时间数据显示仅接受有限数值；未知时长显示 `--:--`，进度和快进均按
  已确认时长裁剪，避免 `NaN`、`Infinity`、越界或显示倒退。

验证结果：

- `docker compose exec -T api pytest apps/api/tests/test_sync_data_retention.py apps/api/tests/test_repair_regressions.py apps/api/tests/test_sync_partial_rows.py apps/api/tests/test_sync_fast_listing.py -q`：31 passed，1 warning。
- `docker compose exec -T web pnpm --filter @sio/web test -- --run`：19 个测试文件、71 个测试通过。
- `docker compose exec -T api ruff check apps/api/app/services/sync.py apps/api/app/services/monitoring.py apps/api/app/tasks/monitoring.py apps/api/tests/test_sync_data_retention.py`：通过。
- `docker compose build web && docker compose up -d web`：Next.js 生产构建、TypeScript、全部路由生成通过，web 容器已更新。

## 2026-08-14 本地字幕翻译 400 修复与真实队列验证

- 根因是 LibreTranslate 1.9.6 实际加载的中文模型代码为 `zh-Hans`，而应用
  发送了 `zh`；同时平台自动字幕 `und-auto` 被错误压缩成 `und`，服务无法识别。
- Provider 出站请求现在将 `zh/zh-CN/zh-Hans` 统一映射为 `zh-Hans`，将
  `und-auto/und/unknown` 映射为 `auto`；UI 和媒体清单仍保存产品语言值 `zh`。
- 翻译服务返回 HTTP 错误时，任务日志会保留服务响应正文，便于定位真实语言
  配对或模型问题，不再只显示 `400 BAD REQUEST`。
- 真实前端作品 `The Sound That Sent MLB Players RUNNING` 重新发起字幕生成后，
  `subtitle-worker` 实际消费任务并完成 7 条翻译轨道，7 次请求全部 HTTP 200，
  `translation_errors=[]`，任务状态 `succeeded`，耗时约 33 秒；页面滚动日志
  展示了全部目标语种的生成过程和完成状态。

验证结果：

- `docker compose exec -T api pytest apps/api/tests/test_translation_provider.py apps/api/tests/test_subtitle_timeline.py apps/api/tests/test_subtitle_tools.py -q`：11 passed，1 warning。
- `docker compose exec -T api ruff check apps/api/app/providers/translation/http.py apps/api/app/tasks/subtitles.py apps/api/tests/test_translation_provider.py`：通过。
- API 容器真实调用 `und-auto → zh`：成功返回中文分段；subtitle-worker 实际任务日志：7 个 HTTP 200、7 条轨道、无翻译错误。
