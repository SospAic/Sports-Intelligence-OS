# 平台采集、凭证与监控任务

更新日期：2026-07-29

## 1. 条件使用关系

每个字段和平台都必须单独判定，不能因为某个平台有一种可用方式，就默认允许采集该平台的全部字段。

```text
需要某项数据
  ├─ 官方 API/OAuth 是否提供且当前授权范围足够？
  │    └─ 是：必须使用 api Provider
  ├─ 是否存在官方 RSS、导出报表或已获准接口？
  │    └─ 是：使用对应 Provider，保留来源与导入记录
  ├─ 是否为无需登录的公开页面？
  │    └─ 同时确认公开访问、条款/许可、robots/许可、字段必要性、
  │       频率和限流后，才使用 public_page Playwright 抽样
  ├─ 是否为用户拥有或明确授权的账号后台？
  │    ├─ 可自动登录：使用 authorized_login
  │    └─ 已有授权会话：使用 authorized_session/storage_state_json
  └─ 均不满足：停止自动采集并记录能力缺口；可以新增经过单独审查的
       Provider，但不得绕过验证码、2FA、登录安全、访问控制或平台限制
```

优先级不是回退猜测，而是能力选择：官方接口能提供的字段不会改用浏览器；浏览器模式只补官方接口确实不提供或当前授权不足的必要字段。系统不会把抓取时间伪装成发布时间，也不会把派生分数标成平台原始指标。

## 2. 四种可选采集模式

| 模式 | 适用范围 | 凭证与限制 |
| --- | --- | --- |
| `api` | 官方 API/OAuth | Key/Token 加密保存；权限不足时明确失败 |
| `public_page` | 经确认可采集的无需登录公开页 | 必须保存合规确认、频率、页数/条数限制与来源 URL |
| `authorized_login` | 用户拥有或明确授权账号的自动登录 | 用户名/密码加密；隔离浏览器上下文；遇验证码/2FA立即停止 |
| `authorized_session` | 已授权 Playwright 会话 | `storage_state_json` 加密、隔离、永不回显；校验 JSON 与过期时间 |

同一平台可以保存多类配置，切换当前模式不会删除其他模式的配置。设置页提供“一键撤销登录授权”：清除用户名、密码、`storage_state_json`、会话过期时间和登录确认字段，保留 API 与公开页配置，并自动回退到仍然有效的安全模式。`storage_state_json` 方案本身保留并可继续使用。

历史账号 `metadata.adapter_config` 会迁移到加密的平台凭证表，迁移成功后删除明文；API、日志和前端只返回 `configured_fields`，不回显秘密。

## 3. 当前 Adapter 边界

| 平台 | 官方模式 | 浏览器模式 | 当前边界 |
| --- | --- | --- | --- |
| YouTube | Data API v3 | 公开页/授权登录 | 官方 API 获取频道、公开视频和公开统计；Analytics OAuth 私有指标未实现 |
| TikTok | Display API v2 | 公开页/授权登录/授权会话 | Display API 只访问 Token 所属用户；任意公开账号不伪装成 Research API，需另获 Research API 审批或使用合规公开页模式 |
| 抖音 | 开放平台 API | 公开页/授权登录/授权会话 | Token 权限不足、响应契约异常和登录墙均记录真实错误 |
| Bilibili | 当前无可依赖的官方开放数据 API | 公开页/授权登录/授权会话 | 仅通过已确认的公开页或授权账号浏览器上下文采样，不再把未文档化 WBI 接口标为官方实时 Provider |
| Mock | 无 | 无 | 只用于测试，固定 `source_kind=mock`，绝不参与真实验收 |

TikTok 当前官方实现使用 Display API v2：`GET /v2/user/info/`、`POST /v2/video/list/` 和 `POST /v2/video/query/`。它不具备按任意用户名读取公开账号的能力。

## 4. 同步、来源和错误

平台差异位于 `apps/api/app/adapters/platforms/`，业务服务只依赖统一 DTO、能力声明和错误分类。`sync_runs` 保存 Adapter、排队/开始/结束时间、状态、创建/更新计数、错误码、错误摘要、请求 ID 与元数据；同一账号活动任务幂等复用。

外部实体至少保存：

- `source_kind`：`live`、`imported` 或 `mock`；
- `source_provider`/`provider` 与 `external_id`；
- `source_url`、`fetched_at`/`observed_at`；
- 适用时保存原始响应引用、访问模式和派生指标算法。

认证失败、权限不足、登录墙、验证码/2FA、限流、超时、契约错误与未实现能力分别记录，不自动切换成 Mock。新快照缺少封面时保留上一次有效封面；前端会升级 Bilibili 图片 HTTPS 并禁止 Referer，最终加载失败则完全移除图片，不保留空白占位。

## 5. 趋势中心的数据关系

趋势中心只读取最近 24 小时且 `source_kind=live` 的观测：

1. 已配置平台 Provider 产生真实账号和作品样本；
2. 作品的播放、点赞、评论等平台字段原样保存；
3. 系统从真实标题/描述中提取受控体育词和明确 Hashtag；
4. 话题热度、关键词热度和高潜分均标记 `metric_kind=derived`，并保存算法名、样本量与来源实体；
5. 旧的未验证趋势记录迁移为 `imported/legacy_unverified`，不进入当前趋势看板。

页面中的“视频样本”是样本总数，“高潜视频”按当前平台样本内播放量百分位排序，不表示平台官方认定的爆款。

## 6. 调度与验证

账号同步由 Celery Worker 执行，Beat 扫描到期账号；外部调用具备超时、有限重试、退避、限流与结构化错误。真实数据验收使用：

```powershell
docker compose ps
docker compose exec -T api python /workspace/scripts/real_data_acceptance.py
```

验收脚本读取 `SIO_ACCEPTANCE_*` 或 bootstrap 登录变量，不打印凭证；检查认证 API、真实新闻、活动账号同步、趋势采集、来源标记和仪表盘统计。实际结果与环境限制见 [REAL_DATA_ACCEPTANCE.md](REAL_DATA_ACCEPTANCE.md)。

## 7. 已知限制

- YouTube Analytics OAuth、私有留存/收入/流量来源尚未实现。
- 当前环境 TikTok Token 无效、YouTube 缺少 Key、抖音返回非预期响应；这些链路不能宣称真实同步成功。
- Bilibili 当前公开页触发登录墙，需配置加密自动登录凭证或有效 `storage_state_json`；系统不会绕过验证码或 2FA。
- 平台配额预算、调度随机抖动和分片队列仍待增强。
