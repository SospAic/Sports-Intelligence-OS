# 待处理任务清单

更新时间：2026-07-31。本文只列本轮优化后仍未闭环的事项；已完成内容以 `docs/STATUS.md` 为准。

## P0：需要外部授权或环境条件

1. 配置有效 YouTube Data API Key，并验证频道、上传列表、视频批量统计、配额和错误分类；未完成前不得标记 YouTube 真实成功。
2. 更新 TikTok Display API OAuth Token、抖音开放平台 Token；分别验证官方 API，不得用浏览器公开页成功替代官方 API 验收。
3. 为 Bilibili 提供加密账号凭证或有效 `storage_state_json`，验证自动登录、会话隔离和一键撤销；遇验证码或 2FA 必须停止，不绕过安全机制。
4. 修复 Docker DNS/代理将公网域名映射到 `198.18.0.0/15` 的问题，在 SSRF 校验保持开启的条件下重跑全部 RSS。
5. 配置真实 LLM 和至少一个外部通知渠道，完成可计费生成、Token/成本记录、通知投递、重试和死信端到端验收。

## P1：数据与产品完善

5. 当前垂直产品继续使用 **Sports Intelligence OS**。若未来扩展为全方向内容创作，建议上层品牌改为 **Creator Intelligence OS**，体育能力保留为 Sports Edition；在领域模型抽象完成前不直接改名。

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
