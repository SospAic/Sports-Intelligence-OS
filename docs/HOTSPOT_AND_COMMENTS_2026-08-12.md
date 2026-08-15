# 热点情报中心与热门评论改造记录（2026-08-12）

## 目标与边界

热点中心以最近 24/48/72 小时为可选窗口。只有 `source_kind=live` 的实时样本进入当前面板；作品/话题有发布时间证据时按发布时间过滤，历史旧记录没有发布时间证据时才回退到采集时间。热度、突破分和关键词均标记为 `metric_kind=derived`，不能解释为平台官方榜单。

当前热点数据由已监控账号的真实作品样本、以及已配置 YouTube Data API 时的官方 `mostPopular` 数据组成；新闻模块按事件 `last_update_time` 过滤并按热度排序。TikTok、抖音、Bilibili 没有在本项目中伪装成“任意公开用户的官方全站热榜”，缺少合法公开来源或授权时 UI 显示真实的来源条件。

## 性能与高可用策略

- 热点采集使用 Celery 后台任务，单平台失败隔离，日志保留最近 120 条；面板通过 `/trends/stream` 接收实时快照，并可切换 24/48/72 小时窗口。
- 账号同步的热门评论开关默认关闭。开启后，同步主流程只为评论 enrichment 写入 `queued` 状态并派发独立 Celery 子任务，账号资料、作品目录和指标不会等待评论网络请求。
- 评论子任务单条作品有内部超时，失败只影响该作品；详情页展示 `queued/running/success/empty/failed/unsupported`，不把空结果伪装成成功。
- 评论抓取使用容器实际安装的 yt-dlp 2026.7.4 支持的 `--write-comments`；yt-dlp 不支持 `--max-comments`，Top 20 在应用层按 `like_count + 3 * reply_count` 排序和截取。

## 评论数据

每条评论保留评论 ID、作者名/链接/头像（若来源提供）、正文、点赞数、回复数、评论时间、是否回复、采集时间、平台来源、来源 URL 和元数据。详情页提供 Top 20 展示和手动刷新；账号同步设置中的“抓取热门评论（每条作品 Top 20）”可选开启。

YouTube 评论可通过 yt-dlp 的授权/公开能力获取；TikTok 官方评论字段在 Research API 中需要符合资格并获批的访问范围，普通 Display API 不等价于 Research API。平台不返回评论、需要登录或拒绝访问时，系统保留条件提示，不生成估算评论。

## 验证记录

- `docker compose build api worker beat web`：通过。
- `docker compose up -d`：通过；api、web、worker、beat 健康运行。
- `alembic upgrade head`：通过，当前版本 `20260811_0002`。
- 后端静态检查、compileall：通过。
- 核心 yt-dlp/趋势进度/同步韧性回归：62 passed。
- 热点、同步、设置、下载相关回归：45 passed。
- 监控 API、账号同步端到端、取消和并发保护：24 passed。
- Web Next production build 与 TypeScript：通过。宿主机无 Node 可执行文件，因此未在宿主机直接运行 Vitest。
- 全量测试共收集 453 项；一次 10 分钟全量命令因测试进程未被命令包装回收而超时，随后残留进程与第二次测试并发清空隔离库造成 PostgreSQL deadlock。重启 api 清理残留进程后，相关测试已串行通过；全量套件不宣称通过。

## 参考的官方能力

- [YouTube commentThreads.list](https://developers.google.com/youtube/v3/docs/commentThreads/list)
- [YouTube 评论实现指南](https://developers.google.com/youtube/v3/guides/implementation/comments)
- [TikTok Research API 查询视频评论](https://developers.tiktok.com/doc/research-api-specs-query-video-comments)
- [TikTok Research API codebook](https://developers.tiktok.com/doc/research-api-codebook)
