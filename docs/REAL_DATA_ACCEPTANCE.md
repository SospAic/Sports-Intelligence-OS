# 真实数据验收记录

验收日期：2026-07-30  
环境：本地 Docker Compose（PostgreSQL、Redis、API、Worker、Beat、Web、Caddy）

## 验收结论

本轮验收使用真实网络响应和现有真实平台记录，不使用 Mock 作为成功条件。系统登录、13 个核心鉴权 API、真实 RSS 入库、趋势派生、Dashboard 聚合、来源标记、失败审计和 Chromium 启动均已验证。外部凭证缺失或无效的链路保留真实失败，未伪造成成功。

| 检查项 | 结果 | 数据边界 |
| --- | --- | --- |
| Compose 七服务 | 通过 | API、Web、Worker、Beat、PostgreSQL、Redis、Proxy 健康；Alembic `20260730_0016 (head)` |
| API 容器 Chromium | 通过 | 实际启动 Chromium，不只是检查安装目录 |
| 登录及核心 API | 13/13 通过 | 使用本地管理员会话，凭证未写入输出；中文搜索“世界杯”返回真实作品 |
| 监控账号 | 6 个活动账号 | 3 个 TikTok 浏览器账号本轮成功；2 个 Bilibili 遇登录墙；错误页账号已非破坏性隔离 |
| 作品 | 302 条真实 Bilibili 记录 | 全部 `source_kind=live`；302 条均有封面 URL |
| 趋势视频 | 302 条实时样本 | 来自真实监控作品；高潜分为样本内派生百分位 |
| 趋势话题/关键词 | 各 8 条实时派生记录 | 来源为真实作品标题/描述，保存样本量、算法与来源实体 |
| 新闻 | CBS Sports Headlines、Deadspin 成功 | 本轮新增 59 条、更新 142 次；数据库共 428 条真实文章，首页 100 条均为 `live` |
| 新闻失败 | CBS MLB HTTP 404；ESPN Top `ConnectError` | 保留真实错误、连续失败数、下次退避时间和外部调用记录 |
| 自动化测试 | 通过 | API 78 项、Web 35 项；TypeScript、ESLint、Ruff、Mypy、Next.js 生产构建通过 |

旧趋势表中的 50 条话题、70 条关键词和 20 条视频已非破坏性改标为 `imported/legacy_unverified`，并带 `acceptance_excluded=true`；趋势 API 不再把这些历史记录显示成实时数据。

## 平台同步结果

| 平台 | 本次状态 | 结论 |
| --- | --- | --- |
| Bilibili | 公开页出现登录弹窗 | 历史 302 条真实作品可用于趋势与 UI 验收；增量刷新需配置加密登录或有效 `storage_state_json` |
| TikTok | 浏览器公开页 3 个账号同步成功；官方 API Token 无效 | 两种路径分别保留真实结果；不能把浏览器成功写成 Display API 成功 |
| 抖音 | 响应不是有效 JSON | 当前 Token/上游响应不可用；错误已审计 |
| YouTube | 未配置 API Key | 官方 Data API 路径未执行；不回退到 Mock |

## 运行方式

在 Compose 完全启动后运行：

```powershell
docker compose exec -T api python /workspace/scripts/real_data_acceptance.py
```

脚本读取 `SIO_ACCEPTANCE_EMAIL`、`SIO_ACCEPTANCE_PASSWORD`，缺失时使用容器内 bootstrap 变量；不会打印凭证。它会：

1. 登录并读取工作区；
2. 排队启用的真实新闻源和活动账号；
3. 触发趋势采集；
4. 检查 13 个核心 API 和来源标记；
5. 刷新 Dashboard 聚合。

## 本地网络说明

本机 Docker DNS/代理把部分公网域名解析到 `198.18.0.0/15`，严格 DNS SSRF 检查会拒绝这些地址。真实 RSS 验收期间仅在隔离本地容器运行时将 `SIO_NEWS_SSRF_CHECK_ENABLED=false`；URL 仍拒绝 localhost、私网字面量、嵌入式凭证和敏感查询参数。验收结束后已将运行容器恢复为默认 `true`。生产环境必须保持默认 `true`，并修复 DNS/代理，而不是关闭 DNS 校验。

文章正文二次抓取默认关闭。只有新闻源显式启用 `article_body_scrape_enabled`，且同时确认公开访问、条款/许可、robots/许可、字段必要性和限流后才运行；RSS/Atom 自带正文不受此开关影响。

## 尚未通过的真实验收

- 真实 YouTube Data API、TikTok Display API、抖音开放平台的有效凭证调用；
- Bilibili 加密自动登录和 `storage_state_json` 的用户凭证实测；
- 真实 LLM 可计费生成和外部通知投递；
- 生产 DNS SSRF 校验下的全部 RSS 源兼容性。

这些项目属于外部授权/环境缺口，不影响已通过的本地功能，但不得宣称为真实平台成功。

## 当前部署备注

验收容器已应用 `20260730_0016`、数据隔离、指标、进度、搜索、可靠性和主要 UI 修复。验收后追加的三项纯前端收尾（活动账号平台分布、任务名中文化、同步记录首屏 20 条）本地检查通过，但因桌面环境提权用量上限尚未重建到运行中的 Web 容器。代码无需再修改；下一次具备 Docker 执行权限时运行：

```powershell
docker compose build web
docker compose up -d web
```
