# 待处理任务清单

更新时间：2026-08-17。本文只列当前仍未闭环的事项；已完成内容以 `docs/STATUS.md` 与 `docs/PRODUCT_AUDIT_2026-08-17.md` 为准。

## P0：需要外部授权或环境条件

1. 配置有效 YouTube Data API Key，并验证频道、上传列表、视频批量统计、配额和错误分类；未完成前不得标记 YouTube 真实成功。
2. 更新 TikTok Display API OAuth Token、抖音开放平台 Token；分别验证官方 API，不得用浏览器公开页成功替代官方 API 验收。
3. 为 Bilibili 提供加密账号凭证或有效 `storage_state_json`，验证自动登录、会话隔离和一键撤销；遇验证码或 2FA 必须停止，不绕过安全机制。
4. 修复 Docker DNS/代理将公网域名映射到 `198.18.0.0/15` 的问题，在 SSRF 校验保持开启的条件下重跑全部 RSS。
5. 配置真实 LLM 和至少一个外部通知渠道，完成可计费生成、Token/成本记录、通知投递、重试和死信端到端验收。

## P1：数据与产品完善

5. 产品品牌已统一为 **Content Intelligence OS（内容智能生产平台）**；体育能力作为首期垂直工作区保留，后续可扩展至全品类内容生产。

6. 本轮已完成保存查询、观察性实验和字幕/模型时间段证据定位本地闭环；仍未完成的是关键帧证据索引、授权 Analytics 驱动的真实 A/B/因果分析、正式发布 Adapter，以及约 36 GB 派生指标历史的备份后分批治理。

## LLM 网关集成（已完成）

本轮已完成 LLM 网关接入方案，不再列为待办：

- docker-compose 新增 New API 网关服务（`calciumion/new-api`，profile `llm`，端口 3306），支持多模型聚合、Key 管理和用量统计。
- docker-compose 新增 Chat2API 实验服务（`gpt4free`，profile `llm-experimental`，端口 8020），提供免费实验通道。
- 后端 SSRF 校验新增 `llm_internal_hosts_allowlist` 配置，Docker 内部网关主机名（如 `new-api`、`chat2api`）可绕过公网地址检查。
- 前端 LLM 设置新增"New API 本地网关"和"Chat2API 实验"两个预设。
- 完整文档见 `docs/LLM_GATEWAY.md`。

## 验收纪律

- `live`、`imported`、`mock` 必须继续显著区分；外部凭证缺失只记录未验证，不生成替代成功。
- 新指标必须先进入 `docs/METRIC_CATALOG.md`，保存公式版本、输入来源、缺失处理和置信度，再进入推荐排序。
- 每个任务完成后更新 `docs/STATUS.md` 与本清单，并运行与风险相称的自动化、Docker 和真实数据验收。

---

## 2026-08-06 当前交接入口

最新的模块进度、Docker 运行基线、验证结果、已知限制、关键代码入口和下一位 AI CODER 的执行顺序，统一见 [`docs/HANDOFF-2026-08-06.md`](HANDOFF-2026-08-06.md)。

当前优先级：

1. P0：使用 Docker noVNC 完成四个平台人工登录，并验证加密 Cookie 捕获、会话复用和账号同步闭环。
2. P1：用真实账号/API Key 验收账号同步完整率、新闻源多策略、视频/字幕下载、LLM 模型探测和视频内容搜索。
3. P1：对 1440×900、1280×720、1024×768、390×844 执行主要页面截图回归，继续检查标题、按钮、弹窗、表格和空态。
4. P2：推进分片续跑、来源健康评分、视频片段/关键帧索引、向量召回、人工复核和成本预算。

交接时以当前代码、Docker 实际状态和 `HANDOFF-2026-08-06.md` 为准；本文件此前章节保留为历史待办记录，不应直接当作当前完成度。
