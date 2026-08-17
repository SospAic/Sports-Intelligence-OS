# 工作区账号级访问授权

更新时间：2026-08-17

账号级授权是工作区角色之下的资源范围控制，适用于账号及其关联作品、快照、指标、评论采集、同步和发布记录。

## 规则

- `owner` / `admin` 不受账号授权限制，默认可访问全部账号。
- `editor` / `analyst` / `viewer` 在没有任何授权记录时保持旧版工作区范围，保证已有工作区兼容。
- 为普通成员创建第一条授权后，该成员进入显式范围模式，只能读取已授予账号。
- `viewer` 只能读取；`editor` 可执行账号/作品编辑、同步请求、评论采集和发布归因刷新。
- 账号级授权不等同于频道级权限、通知渠道权限或发布资源权限；后续需要分别建模。
- 所有创建、更新和撤销动作写入 `workspace_access` 审计记录；数据库只保存授权关系，不保存额外秘密。

## API

当前兼容入口均位于 `/api/v1`，工作区通过 `X-Workspace-Id` 解析：

| 方法 | 路径 | 权限 |
| --- | --- | --- |
| GET | `/workspace-account-grants` | owner/admin |
| POST | `/workspace-account-grants` | owner/admin + CSRF |
| DELETE | `/workspace-account-grants/{grant_id}` | owner/admin + CSRF |

创建或更新 body：

```json
{
  "account_id": "账号 UUID",
  "user_id": "活跃工作区成员 UUID",
  "permission": "viewer"
}
```

同一工作区、账号和成员的重复创建采用更新权限语义。owner/admin 目标会被拒绝，因为其默认权限不需要显式授权。越权读取返回 `403 account_access_denied`，只读成员执行写操作返回 `403 account_write_denied`。

## 数据真实性与限制

授权只影响本地工作区的数据访问边界，不会改变外部平台的账号权限，也不会声称获得 YouTube、TikTok、抖音、Bilibili 或发布 API 的权限。频道级/发布资源 ACL、正式发布 Adapter、外部 Analytics 授权仍需后续设计和真实凭证验收。
