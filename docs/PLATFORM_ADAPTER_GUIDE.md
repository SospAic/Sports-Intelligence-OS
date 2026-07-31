# 平台 Adapter 扩展指南

## 契约

实现 `PlatformAdapter` 的配置校验、账号解析、账号/作品读取、公开或授权分析、能力声明和健康检查。返回统一 DTO，不直接写数据库；持久化与派生指标由同步 Service 负责。

每个 Adapter 必须声明：

- 唯一 `key`、显示名称、implemented/skeleton 状态；
- Capabilities 与配置字段，秘密字段标记 `secret`；
- 可能产生的 `source_kind`；
- 超时、有限重试、配额/限流和稳定错误码。

## 数据真实性

- 官方/授权响应使用 `live`；开发合成响应使用 `mock`。
- 不可用字段进入 `unavailable_metrics`，不得推算后伪装成平台原始值。
- 保留 Provider、外部 ID、抓取时间、来源 URL 和适用的原始响应引用。
- 增量游标和时间一律使用 UTC；无时区数据库值在进入 Adapter 前归一化。

## 注册

在平台注册表中注册实例，业务代码通过注册表解析 `adapter_key`。不要在 Service 中写 `if platform == ...`。

## 测试

至少覆盖配置、分页、映射、删除/私有作品、配额、重试、UTC 增量边界、重复同步和能力不支持。真实凭证测试应单独标记且默认不在 CI 执行；Mock 输出必须显著标记。

YouTube 的首期实现与同步语义见 [PLATFORM_SYNC.md](PLATFORM_SYNC.md)。
