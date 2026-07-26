# 新闻 Provider 扩展指南

## 契约与注册

`NewsProvider` 实现来源校验、最新/时间范围读取、文章规范化和健康检查，并通过新闻 Provider 注册表按 `provider_key` 解析。RSS、Atom、Generic JSON Feed 和 Manual 是首期参考实现。

## 规范化要求

- `published_at` 来自来源声明；缺失时保持空，不能使用 `fetched_at` 冒充。
- `event_time` 与发布时间分离。
- 保留 canonical URL、external ID、来源、语言、抓取时间和来源类型。
- Feed 内容只保存 Feed 明确提供的正文/摘要；不自动抓取链接页全文。

## 网络安全

配置阶段拒绝直接私网、环回、链路本地、内嵌凭证和敏感查询参数。每次请求前会重新解析域名并拒绝任一非公网地址，请求也不自动跟随重定向。生产环境仍应通过固定出站代理、网络 ACL 和 DNS 策略建立第二道边界。

## 去重与聚类

Provider 只负责规范化；内容哈希、URL、标题相似度、事件聚类和参数化评分属于新闻 Service。新增 Provider 不得复制这些业务逻辑。

## 测试

使用本地去敏响应覆盖 RSS/Atom/JSON 映射、时区、无发布时间、错误源隔离、分页/范围和 URL 安全。不要把测试 Feed 标记成来自某个未调用的真实媒体。
