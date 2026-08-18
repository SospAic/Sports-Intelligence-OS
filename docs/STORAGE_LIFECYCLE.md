# 媒体存储生命周期治理

媒体目录现在由 Artifact Registry、配额健康检查和显式生命周期策略共同管理。
数据库中的 `media` JSON 仍保留给适配器兼容使用，但页面的“已下载/已生成”只由物理文件校验后的 `MediaArtifact.status=ready` 决定。

## 默认安全边界

- `SIO_MEDIA_LIFECYCLE_ENABLED=false`、`SIO_MEDIA_LIFECYCLE_DRY_RUN=true` 是默认值。
- `GET /api/v1/storage/health` 只读扫描容量、文件数、孤儿文件和制品完整性。
- `GET /api/v1/storage/lifecycle` 只生成候选预览，并写入审计记录，不删除文件。
- 只有 Owner/Admin 通过 CSRF 保护的 `POST /api/v1/storage/lifecycle`，提交 `confirm=true`、`dry_run=false`，并且同时配置 `SIO_MEDIA_LIFECYCLE_ENABLED=true` 与 `SIO_MEDIA_LIFECYCLE_DRY_RUN=false`，才会执行物理删除。
- 每次执行最多处理 `SIO_MEDIA_LIFECYCLE_BATCH_SIZE` 个文件；扫描和删除都不跟随符号链接，并拒绝越过 `SIO_MEDIA_ROOT` 的路径。

## 保留级别

| 级别 | 默认来源 | 生命周期行为 |
| --- | --- | --- |
| `managed` | 账号同步归档的视频、封面、原字幕、info.json | 永不被自动生命周期清理；由管理员显式变更后才可进入临时策略 |
| `temporary` | 按 URL 提交的下载任务 | 超过 `SIO_MEDIA_RETENTION_DAYS` 且没有未来 `retain_until` 时进入候选 |
| `protected` | 管理员手工保护的制品 | 永不被自动生命周期清理 |

孤儿文件只在工作区目录范围内识别，且必须超过 `SIO_MEDIA_ORPHAN_RETENTION_DAYS`；`avatars` 等不属于工作区的目录不会被清理。删除已登记制品时保留数据库行，标记为 `stale` 并保存 `deleted_at` 与原因，以便审计和后续重新下载。

可通过 `PATCH /api/v1/storage/artifacts/{artifact_id}/retention` 设置保留级别或 `retain_until`。该操作与清理操作都写入 `audit_entries`。

## 运行建议

1. 先确认 PostgreSQL、Redis、媒体目录和通知加密密钥已有可恢复备份。
2. 在设置好配额和保留天数后调用预览接口，检查候选路径、数量、大小和跳过原因。
3. 通过小的 `max_files` 执行一批，检查 API 返回的 `deleted_file_count`、`marked_stale_count`、`failed` 和审计记录。
4. 再由 Celery Beat 每小时运行维护任务。任务在策略未启用时直接返回 `skipped_disabled`；启用但保持 dry-run 时只做计划。

自动删除不包含对象存储迁移、重复文件内容寻址去重或跨主机复制。这些需要独立的对象存储和备份基础设施，不能由本地目录清理假装实现。
