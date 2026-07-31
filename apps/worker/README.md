# Worker

`apps/worker` 是 Celery Worker 与 Beat 的进程组合入口。业务任务及共享应用代码位于
`apps/api/app/tasks` 和对应 Bounded Context；Worker 不复制 API 业务逻辑。

Docker Compose 分别启动：

```text
celery -A apps.worker.celery_app:celery_app worker
celery -A apps.worker.celery_app:celery_app beat
```

首期队列为 `maintenance`；后续 Prompt 按架构文档增加 `sync.platform`、
`ingest.news`、`generation`、`automation` 和 `notification`。
