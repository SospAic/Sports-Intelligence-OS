# 统一运营队列

## 已实现范围

信息历史页 `/notifications` 现在把同步、通知投递、后台任务、未解决审核评论、订阅告警和待处理死信合并为一条可操作队列。除原有的每用户已读回执外，工作区成员可以共享维护：

- `open` / `in_progress` / `completed` 处理状态；
- 最多 10 个标签，每个标签最多 32 个字符；
- 工作区成员负责人和截止时间（API 已支持）；
- 工作区共享保存视图；
- 当前筛选结果批量标记为已完成。

队列处理状态和标签不是外部平台数据，所有更新都会写入审计记录；通知投递或同步本身的业务状态不会被改写。

`GET /api/v1/inbox/sla` 按共享 `due_at` 返回逾期、未来窗口内到期、按计划和已完成项。Beat 每 60 秒执行 `app.tasks.system.sweep_inbox_sla`：逾期的开放/处理中项获得 `sla_overdue` 标签并写入一次 `inbox.sla_overdue` 系统事件，恢复截止时间或完成后清除标签；扫描不改变原始业务状态，也不声称外部升级通知已送达。

## API

- `GET /api/v1/inbox/items`：读取审核评论、订阅告警和待处理死信的统一投影；原任务/通知仍通过各自领域接口读取；
- `GET /api/v1/inbox/queue-states?item_key=task:<uuid>&item_key=notification:<uuid>`：读取工作区队列状态；`item_key` 也支持 `editorial_comment`、`subscription_event` 和 `dead_letter`；
- `PATCH /api/v1/inbox/queue-states/{item_key}`：更新单条处理状态、标签、负责人或截止时间；
- `PATCH /api/v1/inbox/queue-states/bulk`：最多更新 100 条；
- `GET/POST/PATCH/DELETE /api/v1/inbox/views`：管理工作区共享保存视图。

写接口均要求 CSRF 和工作区成员角色。保存视图只允许当前实现的筛选字段 `kind`、`status`、`queue_state`、`label`、`unread`，未知字段会被拒绝。负责人必须是当前工作区的活跃成员。

## 数据边界与下一步

当前统一投影已接入未解决评论、匹配/投递异常订阅事件和待重放死信；原业务页面仍是这些实体的权威处理入口，队列只保存共享处理状态、标签、负责人和截止时间，不覆盖原始业务状态。下一步是在明确配置真实通知目标后增加可配置升级策略和 canary；升级动作必须继续保持来源和原业务状态可追溯。
