export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const now = Date.now();
  const then = new Date(value).getTime();
  const diffMs = now - then;
  if (diffMs < 0) return formatDate(value);
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}天前`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}个月前`;
  return `${Math.floor(months / 12)}年前`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

export function sourceKindLabel(value: string): string {
  if (value === "live") return "实时来源";
  if (value === "imported") return "用户导入";
  return value;
}

const SPORT_LABELS: Record<string, string> = {
  general_sports: "综合体育",
  sports: "综合体育",
  basketball: "篮球",
  football: "足球",
  soccer: "足球",
  baseball: "棒球",
  american_football: "橄榄球",
  hockey: "冰球",
  golf: "高尔夫",
  tennis: "网球",
  esports: "电竞",
  motorsport: "赛车",
  combat: "格斗",
  olympics: "奥运",
};

export function sportLabel(value: string | null | undefined): string {
  if (!value) return "综合体育";
  return SPORT_LABELS[value.toLowerCase()] ?? value;
}
