# Sports Intelligence OS 验收标准

文档状态：Prompt 01 验收基线  
更新日期：2026-07-25

## 1. 验收原则

- 验收以可运行证据、自动化测试、API/数据库状态和文档为准，不以静态截图或口头说明为准。
- Mock 可验证契约和 UI，但必须全链路标记；不能代替真实 Provider 集成 smoke test。
- 一个功能的正常、权限、错误、空状态、幂等和审计均满足后，才可标为完成。
- “实现完成但无凭证未做真实验证”和“真实验证通过”是两个不同状态。
- 所有未实现能力显式列出，不显示假按钮或硬编码成功数据。

状态定义：`planned`、`implemented_unverified`、`verified_mock`、`verified_live`、`blocked`、`not_applicable`。

## 2. Prompt 01 文档验收

Prompt 01 只有在以下条件全部满足时完成：

- [x] 业务模块与首期/后续范围清晰，保存在 `PRODUCT_REQUIREMENTS.md`。
- [x] Bounded Context、模块依赖、目标目录、运行组件和部署拓扑已设计。
- [x] `ARCHITECTURE.md` 包含 Mermaid 系统架构图和核心数据流程图。
- [x] `DOMAIN_MODEL.md` 明确聚合、术语、领域事件和关键不变量。
- [x] `DATABASE_DESIGN.md` 明确实体、关系、约束、索引、保留和迁移顺序，没有万能表设计。
- [x] `API_DESIGN.md` 明确 `/api/v1` 资源、错误、分页、幂等、异步状态和权限。
- [x] `ADAPTER_DESIGN.md` 明确 PlatformAdapter、NewsProvider、LLMProvider、NotificationProvider 与注册机制。
- [x] `RULE_ENGINE_DESIGN.md` 包含条件 AST、三值逻辑、窗口、连续、冷却、去重、解释和 Mermaid 触发流程。
- [x] `PROMPT_ENGINE_DESIGN.md` 包含 Prompt/Workflow 版本、九阶段持久化流程和 Mermaid 工作流图。
- [x] `NOTIFICATION_DESIGN.md` 明确渠道接口、投递状态、幂等、重试、SSRF 和首期渠道。
- [x] `SECURITY.md` 明确认证、RBAC、秘密、日志、审计、上传和外部调用安全。
- [x] `ROADMAP.md` 按 Prompt 02–11 给出实施顺序、退出条件和高风险登记。
- [x] 没有新增大量业务代码或提前声明首期功能已实现。

方框表示设计内容已写入，不表示业务功能已实现。

## 3. 首期 Release 1 端到端验收

### 3.1 启动与身份

| ID | Given / When / Then | 必需证据 |
| --- | --- | --- |
| AC-IAM-01 | 给定干净环境和合法 `.env`，运行文档命令后，Web/API/Worker/Beat/PostgreSQL/Redis/Proxy 健康 | Compose 日志、health 检查、自动化 smoke |
| AC-IAM-02 | 初始管理员经受控 bootstrap 创建后可登录、刷新会话和退出 | API/E2E；数据库只见密码/Session 哈希 |
| AC-IAM-03 | 未认证、Viewer、Editor、Admin 对关键端点按权限矩阵得到预期结果 | 参数化授权测试 |
| AC-IAM-04 | 一个工作区成员不能通过猜 UUID 访问另一工作区数据 | 全关键资源跨租户集成测试 |
| AC-IAM-05 | Connection/Channel 秘密写入后 API、日志、审计和导出均不回显 | secret canary 测试 |

### 3.2 平台账号与作品

| ID | Given / When / Then | 必需证据 |
| --- | --- | --- |
| AC-MON-01 | 创建 Mock Connection/Account 后同步，所有账号、作品、快照、事件和 UI 均显示 Mock | 契约、API、E2E |
| AC-MON-02 | 有合法 YouTube 凭证时添加频道并同步，数据来源为 live 且外部 ID/抓取时间可追溯 | 独立 live smoke 报告 |
| AC-MON-03 | 无 YouTube 凭证或凭证无效时，不创建伪 live 数据，运行显示可操作错误 | 集成测试 |
| AC-MON-04 | 同一同步任务重复投递不会重复创建作品或同一观察快照 | 幂等/故障注入测试 |
| AC-MON-05 | 平台不提供的指标显示不可用/null，不显示 0；派生指标有算法版本 | API/UI 契约 |
| AC-MON-06 | 账号/作品列表、详情、筛选、排序、游标分页和历史曲线读取真实 API | E2E |
| AC-MON-07 | 手动与定时同步都有 SyncRun、错误、计数、trace 和系统事件 | API/数据库断言 |

### 3.3 新闻与事件

| ID | Given / When / Then | 必需证据 |
| --- | --- | --- |
| AC-NEWS-01 | 配置允许访问的真实 RSS 后，文章进入列表/详情并保留来源和原链接 | live RSS smoke + API/E2E |
| AC-NEWS-02 | 发布时间缺失时保持 null，抓取时间单独显示 | fixture/集成测试 |
| AC-NEWS-03 | 重复拉取同一条目不创建重复主记录；内容变化创建 Revision | 幂等测试 |
| AC-NEWS-04 | 基础去重结果可解释，不删除不同来源报道，人工关联可覆盖自动结果 | 领域/API 测试 |
| AC-NEWS-05 | 单个失败源不会阻塞其他新闻源，失败有重试上限和系统事件 | 故障注入测试 |

### 3.4 7.9 规则与 Prompt

| ID | Given / When / Then | 必需证据 |
| --- | --- | --- |
| AC-KNOW-01 | 导入指定 7.9 文件后，原文对象、文件元数据和 SHA-256 可验证 | 导入集成测试/校验报告 |
| AC-KNOW-02 | 规则展示为章节/子章节/规则等结构，并可追溯原文位置 | API/E2E + 抽样复核 |
| AC-KNOW-03 | 说明、Why、How、Good/Bad、QA、Rewrite、优先级、强制、适用范围、依赖/冲突、标签均可表达 | schema/编辑 E2E |
| AC-KNOW-04 | 发布版不可原地修改；编辑产生新版本；差异、回滚、审计可见 | 集成/E2E |
| AC-KNOW-05 | Prompt 正文来自数据库 PromptVersion；源码扫描不存在业务 Prompt 硬编码 | 架构测试/源码审查 |
| AC-KNOW-06 | 缺少原文件时系统不得显示“7.9 已完整导入” | 状态/API/UI 测试 |

### 3.5 内容生成

| ID | Given / When / Then | 必需证据 |
| --- | --- | --- |
| AC-GEN-01 | 创建 Run 后固定输入、Workflow、Rule、Prompt、模型和参数版本 | 数据库/API 断言 |
| AC-GEN-02 | Research 到 Final Output 每个阶段有独立状态、尝试、输入输出和错误 | 集成/E2E |
| AC-GEN-03 | 没有联网研究证据时，事实不能标为已联网核实 | 负向测试 |
| AC-GEN-04 | QA 确定性检查字符范围、单行 TTS、Reveal、标题、关键词、文件名和必需产物 | 单元/属性测试 |
| AC-GEN-05 | QA 失败最多按策略重写，不无限调用；达到上限明确失败 | 状态机测试 |
| AC-GEN-06 | Token、用量来源、耗时、价格快照和成本可见；估算不冒充 Provider 报告 | Provider 契约/API |
| AC-GEN-07 | 取消、重复任务、瞬时失败和检查点恢复不覆盖历史步骤或重复采用结果 | 故障注入测试 |
| AC-GEN-08 | 用户可查看最终结构化产物并评分、采用或拒绝 | E2E |

### 3.6 自动化与通知

| ID | Given / When / Then | 必需证据 |
| --- | --- | --- |
| AC-AUTO-01 | 用户可创建并发布 AND/OR/NOT、比较和时间窗的结构化规则 | API/E2E |
| AC-AUTO-02 | 规则 dry-run 返回 Explain Tree 且不产生外部副作用 | 集成测试 |
| AC-AUTO-03 | null/缺样本得到 unknown 而非 0；窗口、乱序和连续语义符合设计 | 单元/属性测试 |
| AC-AUTO-04 | 重复事件、并发 Worker、冷却和去重不会创建重复 Action | 并发/幂等测试 |
| AC-AUTO-05 | 一个真实快照/新闻事件命中自定义规则并创建系统提醒 | 端到端测试 |
| AC-NOTIF-01 | 至少邮件或 Webhook 在用户控制目标真实投递，并有 DeliveryAttempt | live smoke/接收证据 |
| AC-NOTIF-02 | 邮件、Webhook、Telegram、Discord、飞书、钉钉、企业微信各自实现状态与真实验证状态准确 | Provider 矩阵/契约报告 |
| AC-NOTIF-03 | 401/403/429/5xx/timeout 分类正确；unknown 不盲重发 | 故障注入测试 |
| AC-NOTIF-04 | 测试通知显著标记、受权限/限流、写审计 | E2E/审计断言 |

### 3.7 运营、UI 与真实性

| ID | Given / When / Then | 必需证据 |
| --- | --- | --- |
| AC-OPS-01 | 同步、新闻、生成、规则和通知可用 trace 贯穿 API/任务/系统事件 | 集成测试/样例 trace |
| AC-OPS-02 | 敏感配置和发布操作写追加式 AuditEntry，普通用户不能修改 | 权限/数据库测试 |
| AC-UI-01 | 所有关键页面有 loading/empty/error/success，键盘可完成核心路径 | E2E/可访问性测试 |
| AC-UI-02 | UI 使用系统 API，不以硬编码 JSON/静态成功页面冒充功能 | 网络 E2E/源码审查 |
| AC-TRUTH-01 | live/imported/mock 在数据库、事件、API、UI、导出中一致 | 跨层契约测试 |
| AC-TRUTH-02 | 平台原始、系统派生、不可用指标可区分；新闻评分可解释 | API/UI 测试 |

## 4. API 与数据验收

- Alembic 可从空数据库升级到 head；迁移测试不依赖手工 SQL。
- 数据库唯一、外键、CHECK 和发布不可变约束有失败用例。
- OpenAPI 生成客户端通过 TypeScript 检查；CI 检测破坏变更。
- 列表使用稳定游标；过滤和排序 allowlist；深分页不使用不受控 offset。
- POST 副作用 Idempotency-Key 行为一致；同 key 不同 body 返回冲突。
- 业务数据 + Outbox 同事务；Inbox 消费幂等。
- 大文件只存受控对象引用，不把所有原始内容塞入 JSONB。

## 5. 安全验收

- Argon2id、Session 安全属性、撤销/过期、CSRF、CORS、可信代理和登录限速测试通过。
- 全关键端点通过 IDOR/跨工作区/角色矩阵测试。
- SSRF 覆盖 IPv4/IPv6、DNS、重定向、metadata、私网和危险端口。
- XSS、Markdown/HTML、CSV 注入、上传 MIME/路径/压缩炸弹和 Prompt injection 有负向测试。
- 容器非 root（可行处）、生产无 debug、数据库/Redis 不对公网暴露。
- secret scanner、依赖漏洞扫描没有未接受的高危问题。
- 备份完成一次受控恢复演练；恢复后权限和秘密仍有效/可轮换。

## 6. 性能与可靠性基线

在记录测试硬件和数据规模的前提下：

- 不含外部调用的普通列表 API P95 目标 < 500 ms。
- 同步/生成运行不占用 API Worker 到超时；API 返回 202。
- 单 Provider 超时、429 或 5xx 不导致其他 Provider/API 不可用。
- Worker 在任务提交前/外部调用后/数据库提交后崩溃的故障注入不产生不受控重复副作用。
- 队列积压、Provider 错误、同步新鲜度、生成成本和通知失败有可观察指标/事件。

目标未达到时报告真实结果和瓶颈，不修改测试数据掩盖问题。

## 7. 文档验收

Release 1 交付至少包含：

- 中文 README：要求、配置、启动、登录、验证、停止和清理。
- `.env.example`：所有变量、默认和安全说明，无真实秘密。
- 架构/领域/数据库/API/Adapter/规则/Prompt/通知/安全文档与实现一致。
- Provider 能力与真实验证矩阵，明确未实现/未验证字段和平台。
- 迁移、备份恢复、任务队列、日志审计、故障排查和升级说明。
- 测试命令、范围、结果和已知限制。

## 8. Prompt 阶段退出报告模板

每阶段报告必须包含：

1. **完成内容**：具体文件、迁移、API、UI 或测试。
2. **验证**：执行命令、通过/失败/跳过数量、环境。
3. **真实性边界**：哪些是 live、imported、mock；哪些真实 Provider 未验证。
4. **兼容性**：检查了哪些既有流程，是否有迁移/行为变化。
5. **已知限制与风险**：影响、临时缓解和后续阶段。
6. **尚未实现**：不得省略计划中能力。
7. **下一阶段入口**：只指向严格顺序中的下一 Prompt。

## 9. Release 1 最终判定

以下任一情况存在时不得宣称首期完成：

- 只能打开静态页面，无法经 API、持久化和 Worker 完成关键路径；
- 以 Mock 测试代替所有真实 RSS/YouTube/通知/LLM 集成声明；
- 7.9 只有一个不可编辑文本字段或缺原文却显示完整导入；
- Prompt 硬编码在 Python 或生成只有一次模型调用；
- 前端持有 Token 并直连第三方；
- 规则能重复通知、无冷却/去重/审计；
- 跨工作区越权、秘密泄露或阻断级安全问题未修复；
- 文档/状态把未实现能力写成已完成。

Release 1 完成需 Prompt 10 验收、Prompt 11 高优先级问题清零并通过最终回归。
