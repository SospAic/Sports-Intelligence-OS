# 统一运营队列

## 已实现范围

信息历史页 `/notifications` 现在把同步、通知投递和后台任务合并为一条可操作队列。除原有的每用户已读回执外，工作区成员可以共享维护：

- `open` / `in_progress` / `completed` 处理状态；
- 最多 10 个标签，每个标签最多 32 个字符；
- 工作区成员负责人和截止时间（API 已支持）；
- 工作区共享保存视图；
- 当前筛选结果批量标记为已完成。

队列处理状态和标签不是外部平台数据，所有更新都会写入审计记录；通知投递或同步本身的业务状态不会被改写。

## API

- `GET /api/v1/inbox/queue-states?item_key=task:<uuid>&item_key=notification:<uuid>`：读取工作区队列状态；
- `PATCH /api/v1/inbox/queue-states/{item_key}`：更新单条处理状态、标签、负责人或截止时间；
- `PATCH /api/v1/inbox/queue-states/bulk`：最多更新 100 条；
- `GET/POST/PATCH/DELETE /api/v1/inbox/views`：管理工作区共享保存视图。

写接口均要求 CSRF 和工作区成员角色。保存视图只允许当前实现的筛选字段 `kind`、`status`、`queue_state`、`label`、`unread`，未知字段会被拒绝。负责人必须是当前工作区的活跃成员。

## 数据边界与下一步

当前队列实体为 `task` 和 `notification`，评论线程、订阅告警和死信仍通过各自页面管理，尚未伪装成已经统一的队列项。下一步可在稳定的 item-key 契约上增加 `editorial_comment`、`subscription_event` 和 `dead_letter` 适配器，并补 SLA 到期扫描与升级通知；这些扩展必须继续保持来源和原业务状态可追溯。

