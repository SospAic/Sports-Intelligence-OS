export const OPERATION_CATEGORY_LABELS: Record<string, string> = {
  platform_sync: "平台同步",
  news_sync: "新闻同步",
  generation: "内容生成",
  worker: "通用 Worker",
};

export const OPERATION_STATUS_LABELS: Record<string, string> = {
  never: "尚未同步",
  queued: "排队中",
  pending: "等待中",
  running: "执行中",
  syncing: "同步中",
  retrying: "等待重试",
  success: "成功",
  degraded: "部分同步",
  completed: "完成",
  failed: "失败",
  error: "错误",
  disabled: "已停用",
  skipped: "已跳过",
};

const TASK_PROVIDER_LABELS: Record<string, string> = {
  rss: "RSS 新闻采集",
  atom: "Atom 新闻采集",
  generic_json: "JSON 新闻采集",
  tiktok: "TikTok 官方 API",
  tiktok_browser: "TikTok 浏览器采集",
  tiktok_ytdlp: "TikTok（yt-dlp）",
  bilibili_browser: "Bilibili 浏览器采集",
  youtube: "YouTube 官方 API",
  youtube_browser: "YouTube 浏览器采集",
  youtube_ytdlp: "YouTube（yt-dlp）",
  douyin_ytdlp: "抖音（yt-dlp）",
};

const TASK_TARGET_LABELS: Record<string, string> = {
  account: "账号资料",
  account_contents: "作品列表",
  content_item: "作品指标",
};

export function operationTaskLabel(value: string): string {
  const [provider, target] = value.split(":");
  const providerKey = provider ?? value;
  const providerLabel = TASK_PROVIDER_LABELS[providerKey] ?? providerKey;
  return target
    ? `${providerLabel} · ${TASK_TARGET_LABELS[target] ?? target}`
    : providerLabel;
}
