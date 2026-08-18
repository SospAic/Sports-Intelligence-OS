# 视频内容搜索技术说明书

## 1. 目标与非目标

### 目标

用户输入“视频里出现了什么、说了什么、发生在什么时间”的自然语言描述，系统按计划在四个平台发现候选视频，调用视频理解器读取内容，返回带证据时间戳的结果，并保留完整运行审计。

### 非目标

- 不以标题、简介、标签或作者名作为最终命中条件。
- 不绕过登录墙、验证码、限流、DRM 或平台安全机制。
- 不将没有真实分析器返回的候选标记为 `matched`。
- 不用模拟数据冒充真实平台数据。

## 2. 核心数据契约

### SearchPlan

```text
id, workspace_id, name, query_text
platforms: [youtube, tiktok, douyin, bilibili]
status: active | paused | error
interval_seconds, next_run_at, max_candidates, min_match_score
content_mode: visual_audio | visual_only | audio_visual_text
analyzer_key, last_error, last_run_at
```

### SearchRun

```text
id, plan_id, task_id
status: queued | running | stopping | completed | partial | failed | stopped
candidate_count, analyzed_count, matched_count, rejected_count
started_at, finished_at, stop_requested, error_detail
```

### SearchCandidate

```text
id, plan_id, last_run_id, platform, external_id, canonical_url
title, author_name, cover_url, published_at
content_match_status: discovered | analyzing | matched | rejected | unavailable | failed
match_score, evidence_json, content_text
analysis_provider, analysis_model, source_kind, source_provider
source_url, fetched_at, analyzed_at, error_detail
```

最终命中必须同时满足：

```text
content_match_status == "matched"
and match_score >= plan.min_match_score
and evidence_json.segments.length > 0
and evidence_json.match_basis 不为空
```

## 3. 处理流程

```text
定时器/手动触发
        ↓
创建 SearchRun（可停止）
        ↓
按平台发现候选 URL（只做候选，不做最终命中）
        ↓
canonical_url 去重 + 写入 source_kind/provider
        ↓
视频理解器读取画面、音频、字幕/OCR
        ↓
结构化解析：match、score、segments、visual/audio evidence
        ↓
严格判定 matched/rejected/unavailable/failed
        ↓
更新运行统计、审计和 next_run_at
        ↓
前端按证据检索、过滤、打开原视频、复核
```

## 4. 分析器接口

```python
class VideoContentAnalyzer(Protocol):
    key: str
    supported_platforms: frozenset[str]

    async def analyze(
        self,
        *,
        video_url: str,
        platform: str,
        query: str,
        metadata: dict[str, Any],
    ) -> VideoAnalysisResult: ...
```

首个实现是 Gemini Interactions REST 适配器。它对公开 YouTube URL 使用视频输入，并要求模型返回 JSON；提示词明确禁止依据标题或描述命中。其它来源如果没有合法可读取的媒体 URI，会返回 `unavailable`，不会静默降级为标题匹配。

## 5. 平台适配边界

发现层与理解层分离。一个平台可以“能发现、不能理解”，这时 UI 显示候选数和不可用原因，但结果页不会把它列为内容命中。平台扩展只需实现来源适配器和能力声明，不应在业务服务中堆积平台名称分支。

## 6. 检索与索引演进

### 第一阶段

- PostgreSQL JSON 保存结构化证据。
- `content_text` 保存转写/视觉描述/OCR 的规范化文本。
- 平台、状态、分数、时间和计划建立索引。
- 结果仅允许按证据状态和分数筛选。

### 第二阶段

- 将视频切成带时间段的 `content_segments`。
- 为文本、画面和音频特征提供 embedding provider。
- 使用 pgvector 或外部向量索引执行跨语言语义召回。
- 保留原始证据和模型版本，向量只作为召回层。

## 7. 调度、可靠性与成本

- Beat 每 60 秒扫描到期计划。
- 单个计划每次最多处理配置的候选数，默认值受服务端上限约束。
- 候选按 URL 去重，运行按候选提交进度，避免单个失败导致全量丢失。
- `stop_requested` 是协作式停止；正在执行的外部请求在超时后退出。
- 外部请求有超时、有限重试和结构化错误。
- 计划、运行和候选的状态均可查询；错误不可只写日志不落库。

## 8. 安全与合规门禁

- API Key 只允许来自 Secret 环境变量，不写数据库明文、不写日志。
- 外部 URL 必须是公网可访问地址，禁止访问内网、回环、云元数据地址。
- 只处理公开或已授权媒体；不自动绕过验证码、登录或反爬。
- 结果展示 `source_kind=live/imported/mock`，Mock 只用于测试。
- 已通过内容证据核验的候选可调用 `POST /api/v1/video-search/results/{candidate_id}/topic` 加入选题库；该操作保留候选 URL、Provider、抓取/分析时间、匹配分数和原始证据，使用候选 UUID 作为手工选题的 `source_id`，不把外部视频伪装成已接入的监控作品。
- 证据允许人工复核；模型输出不是事实认证。

## 9. 验收标准

1. 创建计划后能看到四个平台能力状态和定时配置。
2. 手动运行生成可查询的 SearchRun；单个平台失败不影响其他平台状态。
3. 无视频分析器时候选为 `unavailable`，不得出现伪造 `matched`。
4. 分析器命中时必须有分数、来源、分析器和至少一个带时间戳证据。
5. 停止操作能将运行置为 stopping/stopped，并保留已处理结果。
6. 页面在桌面和窄屏均不出现横向溢出，长标题单行省略，证据可展开阅读。
7. Docker migration、API、worker、beat、web readiness 和关键页面门禁全部通过。
## 10. 当前运行时实现补充

- YouTube 公开 URL 走 Gemini Interactions 直接视频输入；Bilibili、TikTok、抖音公开候选走受允许域名校验、yt-dlp 下载、ffmpeg 合并/封装和 Gemini Files API 上传，然后统一返回时间戳证据。
- 这是“候选发现”和“内容理解”两层能力：某平台可以发现 URL，不代表已经完成视频阅读；能力面板、运行状态和结果状态必须保留这种差异。
- 文件上传采用 `SIO_VIDEO_SEARCH_MAX_UPLOAD_BYTES` 限制，临时目录不进入媒体归档；上传文件在分析结束后请求删除，失败时仍清理本地临时目录。
- Gemini 未配置 Key、平台被登录墙/反爬拦截、材料化失败或分析失败时，任务只记录 `unavailable`/`failed`/`partial`，不得升级为 `matched`。
