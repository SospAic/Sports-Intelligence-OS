# 可靠性 SLO 与规则回放

## 可靠性 SLO

`GET /api/v1/reliability/slo?window_minutes=1440` 返回当前工作区窗口内已经持久化的同步运行、外部调用、通知投递尝试、后台任务和统一运营队列统计。

指标是 `metric_kind=derived` 的内部运行证据，不是第三方平台可用性证明。没有记录时显示“无结果”，系统不会用 Mock、估算或平台成功假设补齐。平台公开页、私有 Analytics、外部通知目标和 LLM 的真实可用性仍需对应凭证与授权 canary。

页面入口为“运维 → 可靠性 SLO”。窗口支持 1 小时、24 小时和 7 天；平均延迟只使用实际记录的开始/结束时间或 provider 返回的 duration，缺失时保持为空。

## 规则回放

`POST /api/v1/automations/replay` 使用指定规则或当前工作区已启用规则对一组事实执行只读条件回放。它返回条件解释树、匹配结果和动作计划，但不会写入 `automation_evaluations`、改变运行时冷却状态、创建通知/生成任务或调用外部 Provider。

`source_kind` 仍必须是 `live` 或 `imported`，表示输入事实的来源；回放本身不是新的平台观测，也不应当被当作真实触发成功。正式事件仍使用 `/automations/evaluate`，并接受其幂等、冷却、去重和动作执行约束。

## 仍需外部条件的验收

- YouTube、TikTok、抖音、Bilibili 的真实凭证 canary；
- 真实通知渠道与 LLM 的外部请求、限流和恢复时间；
- 生产 PostgreSQL/Redis 备份恢复和跨主机 HA 演练。

这些边界必须记录为 `blocked_no_credentials` 或基础设施阻断，不得用本地 SLO 或规则回放结果冒充完成。
