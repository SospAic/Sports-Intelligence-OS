# 派生指标存储生命周期

`derived_metrics` 是由账号/作品快照可重复计算得到的派生数据，不是平台原始事实。历史指标对趋势分析有价值，但不能随每次同步无限追加。

## 当前策略

- 同一账号同步在同一个 `SIO_DERIVED_METRICS_BUCKET_SECONDS` 时间桶内重复计算时，复用该桶并替换当前桶记录；默认桶为 1 小时。
- 原始 `account_snapshots`、`content_snapshots` 不因该策略删除，仍是可追溯的事实来源。
- Beat 每日运行 `app.tasks.system.cleanup_derived_metrics`，默认只统计过期候选，不删除数据。
- 默认保留窗口为 30 天；只有同时设置 `SIO_DERIVED_METRICS_CLEANUP_ENABLED=true` 和 `SIO_DERIVED_METRICS_CLEANUP_DRY_RUN=false` 才会按批次删除过期派生指标。
- 删除前必须完成数据库备份、确认指标可由快照重算，并在维护窗口观察删除批次和磁盘回收情况。

## 当前运行态发现

2026-08-17 只读检查发现当前数据库 `derived_metrics` 约 47,655,391 行、占用约 36 GB，增长主要来自历史同步重复计算。完整 `pg_dump` 因此可能达到 GB 级；本轮没有删除这些数据，也没有把未完成的完整恢复演练标记为成功。应用数据卷未修改。

## 验证边界

测试覆盖同一时间桶的重复计算只保留一组当前指标。恢复演练脚本使用文件流式 I/O，避免把大备份读入内存；生产级全量恢复仍需在具备足够临时磁盘、备份存储和维护窗口的环境中执行。
