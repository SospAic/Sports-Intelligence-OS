"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Calendar,
  Check,
  CircleStop,
  Database,
  FileDown,
  Layers,
  Network,
  Play,
  Plus,
  Printer,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Video,
} from "lucide-react";
import { Fragment, type ReactNode, useMemo, useRef, useState } from "react";

import { useWorkspace } from "@/components/app-shell";
import {
  Badge,
  PageHeader,
  Panel,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { useToast } from "@/components/toast";
import { apiRequest } from "@/lib/browser-api";
import {
  evidenceLocatorUrl,
  evidenceWindowFromMs,
  formatEvidenceTime,
  type EvidenceWindow,
} from "@/lib/video-evidence";

/* ========================================================================== */
/*  Types                                                                      */
/* ========================================================================== */

/* ----- LLM (video-search) contracts ----- */
type PlatformKey = "youtube" | "tiktok" | "douyin" | "bilibili";
type CapabilityResponse = {
  analyzer_key: string;
  configured: boolean;
  model: string | null;
  platforms: Record<string, { discovery: boolean; content_analysis: boolean; status: string }>;
  notice: string | null;
};
type LLMPlan = {
  id: string;
  name: string;
  query_text: string;
  platforms: PlatformKey[];
  status: string;
  interval_seconds: number;
  next_run_at: string;
  last_run_at: string | null;
  max_candidates: number;
  min_match_score: number;
  analyzer_key: string;
  last_error: string | null;
};
type LLMRun = {
  id: string;
  plan_id: string;
  status: string;
  candidate_count: number;
  analyzed_count: number;
  matched_count: number;
  rejected_count: number;
  stop_requested: boolean;
  started_at: string | null;
  finished_at: string | null;
};
type Candidate = {
  id: string;
  plan_id: string;
  platform: PlatformKey;
  canonical_url: string;
  title: string | null;
  author_name: string | null;
  cover_url: string | null;
  content_match_status: string;
  match_score: number | null;
  evidence: {
    summary?: string;
    segments?: Array<{ start_seconds?: number; end_seconds?: number; evidence?: string }>;
    visual_tags?: string[];
    actions?: string[];
    objects?: string[];
    ocr_text?: string[];
    transcript_summary?: string | null;
    match_basis?: string[];
  };
  analysis_provider: string | null;
  analysis_model: string | null;
  source_kind: string;
  source_provider: string;
  error_detail: string | null;
  analyzed_at: string | null;
};

/* ----- Local (semantic-search) contracts ----- */
type SearchMode = "hybrid" | "vector" | "keyword";
type ChunkKind = "meta" | "subtitle" | "transcript";
type StatusResponse = {
  enabled: boolean;
  backend: string;
  model: string | null;
  dimension: number;
  embedded_chunks: number;
  embedded_items: number;
  pending_items: number;
  latest_embedded_at: string | null;
  freshness: "fresh" | "stale" | "empty";
  freshness_detail: string;
  chunk_kinds: Record<string, number>;
};
type SearchChunk = {
  chunk_kind: string;
  chunk_index: number;
  text: string;
  start_ms: number | null;
  end_ms: number | null;
  source_ref: string | null;
  distance: number | null;
  score: number;
  matched_by: string[];
};
type SearchHit = {
  content_item_id: string;
  title: string;
  canonical_url: string;
  cover_url: string | null;
  platform_id: string;
  account_id: string;
  published_at: string | null;
  duration_seconds: number | null;
  score: number;
  best_chunk: SearchChunk;
  chunks: SearchChunk[];
};
type SearchResponse = {
  query: string;
  mode_requested: SearchMode;
  mode_used: SearchMode;
  degraded: boolean;
  model: string | null;
  total: number;
  items: SearchHit[];
  took_ms: number;
};

/* ----- shared option sources ----- */
type PlatformOption = { id: string; key: string; name: string };
type AccountItem = { id: string; display_name: string | null; username: string | null };

type PageResponse<T> = { items: T[]; total: number; page: number; page_size: number };

type Engine = "llm" | "local";
type ResultFilter = "all" | "llm" | "local";

/* The shared, engine-agnostic plan inputs captured in the plan form. */
type PlanDraft = {
  queryText: string;
  platformKeys: PlatformKey[];
  platformIds: string[];
  accountIds: string[];
  dateFrom: string;
  dateTo: string;
  candidates: number;
  name: string;
};

/* ----- unified result shape (both engines normalized) ----- */
type UnifiedResult = {
  engine: Engine;
  id: string;
  candidateId?: string;
  title: string;
  url: string;
  cover_url: string | null;
  platformLabel: string;
  accountLabel: string;
  published_at: string | null;
  duration_seconds: number | null;
  scoreValue: number;
  scoreText: string;
  snippet: ReactNode;
  /** Plain-text twin of `snippet`, kept for payloads that cannot carry JSX. */
  snippetText: string;
  badges: Array<{ label: string; tone: "info" | "success" | "warning" | "danger" | "neutral" }>;
  meta: string;
  evidenceWindow?: EvidenceWindow;
  sentiment?: "positive" | "neutral" | "negative";
  heat?: number;
};

/* ----- report export contracts ----- */
type ExportFormat = "md" | "pdf";
type ExportResponse = {
  filename: string;
  markdown: string;
  html_document: string;
  generated_at: string;
  total: number;
};

type SummaryResponse = {
  total: number;
  platform_distribution: Record<string, number>;
  engine_distribution: Record<string, number>;
  top_items: Array<{ id: string; title: string; platform: string; engine: string; score: number }>;
  items: Array<{ id: string; sentiment: "positive" | "neutral" | "negative"; heat: number }>;
  llm_summary: string | null;
  llm_available: boolean;
};

/* ========================================================================== */
/*  Constants / labels                                                         */
/* ========================================================================== */

const PLATFORM_KEYS: Array<{ key: PlatformKey; label: string }> = [
  { key: "youtube", label: "YouTube" },
  { key: "tiktok", label: "TikTok" },
  { key: "douyin", label: "抖音" },
  { key: "bilibili", label: "Bilibili" },
];

const MODE_OPTIONS: Array<{ key: SearchMode; label: string; hint: string }> = [
  { key: "hybrid", label: "混合", hint: "向量 + 关键词，RRF 融合排序" },
  { key: "vector", label: "向量", hint: "仅语义向量召回" },
  { key: "keyword", label: "关键词", hint: "仅文本关键词召回" },
];

const CHUNK_KIND_LABELS: Record<ChunkKind, string> = {
  meta: "元数据",
  subtitle: "字幕",
  transcript: "转写",
};

const MATCH_LABELS: Record<string, string> = { vector: "向量", keyword: "关键词" };

const LLM_STATUS_LABELS: Record<string, string> = {
  active: "运行中",
  paused: "已暂停",
  error: "需处理",
  queued: "排队中",
  running: "分析中",
  stopping: "停止中",
  completed: "已完成",
  partial: "部分完成",
  stopped: "已停止",
  failed: "失败",
  matched: "内容命中",
  rejected: "内容不匹配",
  unavailable: "分析不可用",
  discovered: "待分析",
  analyzing: "分析中",
};

/* ========================================================================== */
/*  Helpers                                                                    */
/* ========================================================================== */

function formatInterval(seconds: number): string {
  if (seconds < 3600) return `每 ${Math.round(seconds / 60)} 分钟`;
  if (seconds % 86400 === 0) return `每 ${seconds / 86400} 天`;
  return `每 ${Math.round(seconds / 3600)} 小时`;
}

function formatDuration(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "时长未知";
  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "日期未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "日期未知";
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function formatNumber(value: number): string {
  return value.toLocaleString("en-US");
}

function firstLlmEvidenceWindow(
  segments: Candidate["evidence"]["segments"],
): EvidenceWindow | undefined {
  for (const segment of segments ?? []) {
    const window = evidenceWindowFromMs(
      typeof segment.start_seconds === "number" ? segment.start_seconds * 1000 : null,
      typeof segment.end_seconds === "number" ? segment.end_seconds * 1000 : null,
      "模型标注时间段",
    );
    if (window) return window;
  }
  return undefined;
}

function llmTone(status: string): "neutral" | "success" | "warning" | "danger" | "info" {
  if (["matched", "completed", "active"].includes(status)) return "success";
  if (["unavailable", "partial", "stopping", "analyzing"].includes(status)) return "warning";
  if (["failed", "error"].includes(status)) return "danger";
  return "info";
}

/** Lightweight query-term highlighting (case-insensitive, regex-safe). */
function highlight(text: string, query: string): ReactNode {
  const terms = query.trim().split(/\s+/).filter((term) => term.length >= 2);
  if (terms.length === 0) return text;
  const pattern = new RegExp(`(${terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  const parts = text.split(pattern);
  return parts.map((part, index) =>
    pattern.test(part) ? (
      <mark key={index} className="rounded bg-cyan-400/20 px-0.5 text-cyan-200">
        {part}
      </mark>
    ) : (
      <Fragment key={index}>{part}</Fragment>
    ),
  );
}

function accountLabel(account: AccountItem | undefined): string {
  if (!account) return "未知账号";
  return account.display_name || account.username || "未命名账号";
}

/** Save a server-rendered text artefact through an object URL. */
function downloadTextFile(content: string, filename: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** PDF path: no PDF dependency ships with the app, so the server-rendered
 *  report is printed from an offscreen iframe and the browser's print dialog
 *  does the "save as PDF" step. An iframe (rather than window.open) keeps
 *  popup blockers out of the way since the click already awaited a request. */
function printHtmlDocument(html: string): void {
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;";
  frame.srcdoc = html;
  frame.onload = () => {
    const view = frame.contentWindow;
    if (!view) {
      frame.remove();
      return;
    }
    const cleanup = () => frame.remove();
    view.addEventListener("afterprint", cleanup, { once: true });
    /* Fallback for engines that never fire afterprint on frames. */
    window.setTimeout(cleanup, 60_000);
    view.focus();
    view.print();
  };
  document.body.append(frame);
}

/* ========================================================================== */
/*  Component                                                                  */
/* ========================================================================== */

export function VideoSearchClient() {
  const { workspaceId } = useWorkspace();
  const queryClient = useQueryClient();
  const { notify } = useToast();

  /* ----- active engine tab ----- */
  const [engineTab, setEngineTab] = useState<Engine>("llm");
  /* Captured when the plan form is submitted so the LLM/local queries and
     results only start fetching once a plan exists. The whole page is laid out
     top-to-bottom (plan form -> engine tabs -> merged results); nothing is
     hidden behind a step gate. */
  const [planDraft, setPlanDraft] = useState<PlanDraft | null>(null);

  /* ----- SHARED plan inputs (identical across engines) ----- */
  const [queryText, setQueryText] = useState("");
  const [selectedPlatformKeys, setSelectedPlatformKeys] = useState<PlatformKey[]>([]);
  const [accountIds, setAccountIds] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [candidates, setCandidates] = useState(20);
  const [name, setName] = useState("");

  /* ----- LLM-only config ----- */
  const interval = 3600;
  const minScore = 0.65;
  /* ----- Local-only config ----- */
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [chunkKinds, setChunkKinds] = useState<ChunkKind[]>([]);
  const [limit, setLimit] = useState(20);

  /* ----- action / result state ----- */
  const [submitting, setSubmitting] = useState(false);
  const [searching, setSearching] = useState(false);
  const [plan, setPlan] = useState<LLMPlan | null>(null);
  const [localResults, setLocalResults] = useState<SearchResponse | null>(null);
  const [resultFilter, setResultFilter] = useState<ResultFilter>("all");
  /** Which report format is currently being rendered server-side, if any. */
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [creatingTopicId, setCreatingTopicId] = useState<string | null>(null);

  /* ----- auto-scroll anchors: after each step's submit, glide to the next section ----- */
  const section2Ref = useRef<HTMLDivElement>(null);
  const section3Ref = useRef<HTMLDivElement>(null);
  const scrollToSection = (ref: { current: HTMLDivElement | null }) => {
    requestAnimationFrame(() => {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  /* ----- LLM data ----- */
  const capabilities = useQuery<CapabilityResponse>({
    queryKey: ["video-search-capabilities", workspaceId],
    queryFn: () => apiRequest<CapabilityResponse>("/video-search/capabilities", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
    staleTime: 30_000,
  });
  const plans = useQuery<PageResponse<LLMPlan>>({
    queryKey: ["video-search-plans", workspaceId],
    queryFn: () => apiRequest<PageResponse<LLMPlan>>("/video-search/plans?page=1&page_size=50", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId) && planDraft != null,
    refetchInterval: 10_000,
  });
  const runs = useQuery<PageResponse<LLMRun>>({
    queryKey: ["video-search-runs", workspaceId],
    queryFn: () => apiRequest<PageResponse<LLMRun>>("/video-search/runs?page=1&page_size=20", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId) && planDraft != null,
    refetchInterval: 5_000,
  });
  const llmResults = useQuery<PageResponse<Candidate>>({
    queryKey: ["video-search-results", workspaceId, "matched"],
    queryFn: () => apiRequest<PageResponse<Candidate>>("/video-search/results?status=matched&page=1&page_size=50", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId) && planDraft != null,
    refetchInterval: 30_000,
  });

  /* ----- Local data ----- */
  const status = useQuery<StatusResponse>({
    queryKey: ["semantic-search-status", workspaceId],
    queryFn: () => apiRequest<StatusResponse>("/semantic-search/status", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
    refetchInterval: 15_000,
  });
  const platforms = useQuery<PlatformOption[]>({
    queryKey: ["semantic-search-platforms", workspaceId],
    queryFn: () => apiRequest<PlatformOption[]>("/monitoring/platforms", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
    staleTime: 300_000,
  });
  const accounts = useQuery<PageResponse<AccountItem>>({
    queryKey: ["semantic-search-accounts", workspaceId],
    queryFn: () => apiRequest<PageResponse<AccountItem>>("/monitoring/accounts?page=1&page_size=200", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
    staleTime: 300_000,
  });

  const latestRunByPlan = useMemo(() => {
    const map = new Map<string, LLMRun>();
    for (const run of runs.data?.items ?? []) {
      if (!map.has(run.plan_id)) map.set(run.plan_id, run);
    }
    return map;
  }, [runs.data?.items]);

  const platformNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const platform of platforms.data ?? []) map.set(platform.id, platform.name);
    return map;
  }, [platforms.data]);

  const platformKeyById = useMemo(() => {
    const map = new Map<string, PlatformKey>();
    for (const platform of platforms.data ?? []) map.set(platform.id, platform.key as PlatformKey);
    return map;
  }, [platforms.data]);

  const accountById = useMemo(() => {
    const map = new Map<string, AccountItem>();
    for (const account of accounts.data?.items ?? []) map.set(account.id, account);
    return map;
  }, [accounts.data]);

  const disabled = !status.data?.enabled;

  const refreshLLM = () => {
    void queryClient.invalidateQueries({ queryKey: ["video-search-plans"] });
    void queryClient.invalidateQueries({ queryKey: ["video-search-runs"] });
    void queryClient.invalidateQueries({ queryKey: ["video-search-results"] });
  };

  const toggle = <T,>(list: T[], value: T, setter: (next: T[]) => void) => {
    setter(list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);
  };

  /* ----- create the shared plan (persisted as an LLM plan) ----- */
  const createPlan = async () => {
    if (!workspaceId) return;
    const selectedKeys = selectedPlatformKeys;
    if (queryText.trim().length < 2 || selectedKeys.length === 0) {
      notify("请输入至少 2 个字符，并选择至少一个平台", "error");
      return;
    }
    /* Capture the shared draft immediately. The page is laid out top-to-bottom,
       so the engine tabs and merged-results sections are already visible; this
       draft just enables the LLM/local queries and the local-search filter. A
       backend plan-persist failure is non-fatal (local search needs no persisted
       plan). */
    const draft: PlanDraft = {
      queryText: queryText.trim(),
      platformKeys: selectedKeys,
      platformIds: selectedPlatformKeys.map((key) => platformKeyById.get(key)).filter((x): x is PlatformKey => x != null),
      accountIds: [...accountIds],
      dateFrom,
      dateTo,
      candidates,
      name: name.trim(),
    };
    setPlanDraft(draft);
    setEngineTab("llm");

    setSubmitting(true);
    try {
      const created = await apiRequest<LLMPlan>("/video-search/plans", {
        method: "POST",
        csrf: true,
        workspaceId,
        body: JSON.stringify({
          name: name.trim() || undefined,
          query_text: queryText.trim(),
          platforms: selectedKeys,
          interval_seconds: interval,
          max_candidates: candidates,
          min_match_score: minScore,
          run_now: false,
        }),
      });
      setPlan(created);
      notify("内容搜索计划已创建，可在下方选择引擎执行", "success");
      refreshLLM();
    } catch (error) {
      /* Non-fatal for the local flow: surface a warning but keep the wizard on
         Step 2 so the user can still run a local semantic search. */
      notify(`计划保存失败（本地检索不受影响）：${(error as Error).message}`, "warning");
    } finally {
      setSubmitting(false);
    }
    scrollToSection(section2Ref);
  };

  const runPlan = async (planId: string) => {
    if (!workspaceId) return;
    try {
      await apiRequest(`/video-search/plans/${planId}/run`, { method: "POST", csrf: true, workspaceId });
      notify("LLM 分析任务已提交", "success");
      refreshLLM();
      scrollToSection(section3Ref);
    } catch (error) {
      notify(`提交失败：${(error as Error).message}`, "error");
    }
  };

  const stopPlan = async (planId: string) => {
    if (!workspaceId) return;
    try {
      await apiRequest(`/video-search/plans/${planId}/stop`, { method: "POST", csrf: true, workspaceId });
      notify("已请求停止，正在收尾当前分析", "success");
      refreshLLM();
    } catch (error) {
      notify(`停止失败：${(error as Error).message}`, "error");
    }
  };

  const createTopicFromCandidate = async (candidateId: string) => {
    if (!workspaceId || creatingTopicId) return;
    setCreatingTopicId(candidateId);
    try {
      const topic = await apiRequest<{ id: string; title: string }>(
        `/video-search/results/${candidateId}/topic`,
        {
          method: "POST",
          csrf: true,
          workspaceId,
          body: JSON.stringify({}),
        },
      );
      notify(`已加入选题库：${topic.title}`, "success");
      void queryClient.invalidateQueries({ queryKey: ["topics"] });
    } catch (error) {
      notify(`加入选题失败：${(error as Error).message}`, "error");
    } finally {
      setCreatingTopicId(null);
    }
  };

  /* ----- Step 2 (local tab): one-shot semantic query reusing plan inputs ----- */
  const runLocalSearch = async () => {
    if (!workspaceId) return;
    const cleaned = queryText.trim();
    if (cleaned.length < 1) {
      notify("请输入检索词", "error");
      return;
    }
    setSearching(true);
    try {
      const body: Record<string, unknown> = {
        query: cleaned,
        mode,
        limit: Math.max(1, Math.min(100, limit)),
        candidates: Math.max(10, Math.min(1000, candidates)),
      };
      if (chunkKinds.length) body.chunk_kinds = chunkKinds;
      const resolvedPlatformIds = selectedPlatformKeys.map((key) => platformKeyById.get(key)).filter((x): x is PlatformKey => x != null);
      if (resolvedPlatformIds.length) body.platform_ids = resolvedPlatformIds;
      if (accountIds.length) body.account_ids = accountIds;
      if (dateFrom) body.published_after = new Date(dateFrom).toISOString();
      if (dateTo) body.published_before = new Date(dateTo).toISOString();
      const response = await apiRequest<SearchResponse>("/semantic-search/query", {
        method: "POST",
        workspaceId,
        body: JSON.stringify(body),
      });
      setLocalResults(response);
      setResultFilter("local");
      scrollToSection(section3Ref);
    } catch (error) {
      const message = (error as Error).message;
      if (message.includes("semantic_search_disabled")) {
        notify("本地检索服务未启用，请在服务端配置 embedding 后端", "error");
      } else {
        notify(`检索失败：${message}`, "error");
      }
    } finally {
      setSearching(false);
    }
  };

  /* ----- unified results: merge both engines ----- */
  const unifiedResults = useMemo<UnifiedResult[]>(() => {
    const list: UnifiedResult[] = [];

    for (const item of llmResults.data?.items ?? []) {
      list.push({
        engine: "llm",
        id: item.id,
        candidateId: item.id,
        title: item.title ?? item.canonical_url,
        url: item.canonical_url,
        cover_url: item.cover_url,
        platformLabel: PLATFORM_KEYS.find((p) => p.key === item.platform)?.label ?? item.platform,
        accountLabel: item.author_name ?? "来源未提供作者",
        published_at: null,
        duration_seconds: null,
        scoreValue: item.match_score ?? 0,
        scoreText: item.match_score != null ? `内容分数 ${Math.round(item.match_score * 100)}%` : "无分数",
        snippet: item.evidence.summary ?? item.error_detail ?? "（暂无内容证据摘要）",
        snippetText: item.evidence.summary ?? item.error_detail ?? "",
        badges: [{ label: LLM_STATUS_LABELS[item.content_match_status] ?? item.content_match_status, tone: llmTone(item.content_match_status) }],
        meta: `${item.source_provider} · ${item.analysis_provider ?? "未分析"}${item.analysis_model ? ` / ${item.analysis_model}` : ""}`,
        evidenceWindow: firstLlmEvidenceWindow(item.evidence.segments),
      });
    }

    if (localResults) {
      for (const hit of localResults.items) {
        list.push({
          engine: "local",
          id: hit.content_item_id,
          title: hit.title || "无标题",
          url: hit.canonical_url,
          cover_url: hit.cover_url,
          platformLabel: platformNameById.get(hit.platform_id) ?? "未知平台",
          accountLabel: accountLabel(accountById.get(hit.account_id)),
          published_at: hit.published_at,
          duration_seconds: hit.duration_seconds,
          scoreValue: hit.score,
          scoreText: `相关度 ${Math.round(hit.score * 100)}%`,
          snippet: highlight(hit.best_chunk.text, localResults.query),
          snippetText: hit.best_chunk.text,
          badges: [
            ...hit.best_chunk.matched_by.map((source) => ({
              label: MATCH_LABELS[source] ?? source,
              tone: (source === "vector" ? "info" : "neutral") as "info" | "neutral",
            })),
            { label: CHUNK_KIND_LABELS[hit.best_chunk.chunk_kind as ChunkKind] ?? hit.best_chunk.chunk_kind, tone: "neutral" },
          ],
          meta: `${formatDate(hit.published_at)} · ${formatDuration(hit.duration_seconds)}`,
          evidenceWindow: evidenceWindowFromMs(
            hit.best_chunk.start_ms,
            hit.best_chunk.end_ms,
            "字幕/转写时间段",
            hit.best_chunk.source_ref,
          ),
        });
      }
    }

    return list.sort((a, b) => b.scoreValue - a.scoreValue);
  }, [llmResults.data?.items, localResults, platformNameById, accountById]);

  const filteredResults = useMemo(() => {
    if (resultFilter === "all") return unifiedResults;
    return unifiedResults.filter((item) => item.engine === resultFilter);
  }, [unifiedResults, resultFilter]);

  /* ----- auto-summary: digest + per-item sentiment/heat (degrades without LLM) ----- */
  const summaryQuery = useQuery<SummaryResponse>({
    queryKey: ["video-search-summary", unifiedResults],
    queryFn: () =>
      apiRequest<SummaryResponse>(`/video-search/summarize`, {
        method: "POST",
        csrf: true,
        workspaceId: workspaceId!,
        body: JSON.stringify({
          query: planDraft?.queryText ?? "",
          items: unifiedResults.map((i) => ({
            id: i.id,
            title: typeof i.title === "string" ? i.title : "",
            snippet: typeof i.snippet === "string" ? i.snippet : "",
            platform: i.platformLabel,
            engine: i.engine,
            score: i.scoreValue,
          })),
        }),
      }),
    enabled: Boolean(workspaceId) && unifiedResults.length > 0,
  });

  const summaryById = useMemo(() => {
    const m = new Map<string, { sentiment: "positive" | "neutral" | "negative"; heat: number }>();
    for (const it of summaryQuery.data?.items ?? []) {
      m.set(it.id, { sentiment: it.sentiment, heat: it.heat });
    }
    return m;
  }, [summaryQuery.data]);

  const llmCount = unifiedResults.filter((item) => item.engine === "llm").length;
  const localCount = unifiedResults.filter((item) => item.engine === "local").length;

  /* ----- Section 3: one-click report export (Markdown / print-to-PDF) -----
     The currently visible results are posted to the server, which renders both
     artefacts, so the report always mirrors the active engine filter. */
  const runExport = async (format: ExportFormat) => {
    if (!workspaceId || exporting) return;
    if (filteredResults.length === 0) {
      notify("没有可导出的结果", "error");
      return;
    }
    setExporting(format);
    try {
      const report = await apiRequest<ExportResponse>("/semantic-search/export", {
        method: "POST",
        csrf: true,
        workspaceId,
        body: JSON.stringify({
          title: planDraft?.name || "体育情报简报",
          query: planDraft?.queryText ?? queryText.trim(),
          mode: localResults?.mode_used ?? "",
          summary: summaryQuery.data?.llm_summary ?? "",
          items: filteredResults.map((item) => ({
            title: item.title,
            url: item.url,
            engine: item.engine,
            platform: item.platformLabel,
            account: item.accountLabel,
            published_at: item.published_at ? formatDate(item.published_at) : "",
            score: item.scoreValue,
            snippet: item.snippetText,
            badges: item.badges.map((badge) => badge.label),
          })),
        }),
      });
      if (format === "md") {
        downloadTextFile(report.markdown, report.filename, "text/markdown;charset=utf-8");
        notify(`已导出 ${report.total} 条结果为 Markdown`, "success");
      } else {
        printHtmlDocument(report.html_document);
        notify("已打开打印视图，选择「另存为 PDF」即可保存", "success");
      }
    } catch (error) {
      notify(`导出失败：${(error as Error).message}`, "error");
    } finally {
      setExporting(null);
    }
  };

  return (
    <main className="mx-auto w-full max-w-[1600px] space-y-6 p-4 lg:p-6">
      <PageHeader
        eyebrow="CONTENT SEARCH"
        title="视频内容搜索"
        description="创建一份内容搜索计划后，可分别用 LLM 智能分析或本地语义检索两种方式执行，结果统一合并展示。LLM 读取画面/语音/OCR 给出内容证据；本地检索完全本地、不调用 LLM。"
        actions={
          <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-1.5 text-xs text-slate-400">
            <Sparkles size={13} className="text-cyan-400" />
            <span>{capabilities.data?.configured ? `LLM 分析器：${capabilities.data.model ?? capabilities.data.analyzer_key}` : "LLM 分析器未配置"}</span>
          </div>
        }
      />

      {/* ----------------------------- flow orientation ----------------------------- */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <span className="rounded-full bg-cyan-500/15 px-2.5 py-0.5 font-medium text-cyan-200">1 创建内容搜索计划</span>
        <span className="text-slate-700">→</span>
        <span className="rounded-full bg-cyan-500/15 px-2.5 py-0.5 font-medium text-cyan-200">2 选择引擎执行</span>
        <span className="text-slate-700">→</span>
        <span className="rounded-full bg-cyan-500/15 px-2.5 py-0.5 font-medium text-cyan-200">3 合并结果</span>
      </div>

      {/* ====================================================================== */}
      {/*  SECTION 1 — create plan (full-width two columns)                       */}
      {/* ====================================================================== */}
      <section className="grid gap-6 xl:grid-cols-2">
          {/* left: description + platforms + accounts */}
          <Panel className="p-5">
            <div className="mb-5 flex items-start gap-3">
              <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-cyan-400/10 text-cyan-300">
                <Search size={19} />
              </div>
              <div>
                <h2 className="font-semibold text-white">创建内容搜索计划</h2>
                <p className="mt-1 text-xs leading-5 text-slate-500">
                  描述视频中真正要找的画面、动作、声音或口播内容。这份输入在两种引擎间保持一致。
                </p>
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-400">内容描述</label>
                <textarea
                  rows={5}
                  value={queryText}
                  onChange={(event) => setQueryText(event.target.value)}
                  onKeyDown={(event) => {
                    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") void createPlan();
                  }}
                  placeholder="例如：视频中出现运动员在雨中完成最后冲刺，并能听到现场观众欢呼"
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-sm leading-6 text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20"
                />
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-400">来源平台（不选 = 全部）</label>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {PLATFORM_KEYS.map((platform) => {
                    const active = selectedPlatformKeys.includes(platform.key);
                    return (
                      <button
                        type="button"
                        key={platform.key}
                        onClick={() => toggle(selectedPlatformKeys, platform.key, setSelectedPlatformKeys)}
                        className={`flex items-center justify-between rounded-xl border px-3 py-2.5 text-sm transition ${
                          active ? "border-cyan-500/70 bg-cyan-500/10 text-cyan-200" : "border-slate-800 bg-slate-950/40 text-slate-500 hover:border-slate-700"
                        }`}
                      >
                        <span className="truncate">{platform.label}</span>
                        {active && <Check size={14} className="shrink-0" />}
                      </button>
                    );
                  })}
                </div>
                <p className="mt-1.5 text-xs text-slate-500">系统支持的全部平台均可选；平台 UUID 由服务端自动解析（本地检索过滤仍生效）。</p>
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-400">账号筛选（不选 = 全部，本地检索生效）</label>
                <select
                  multiple
                  value={accountIds}
                  onChange={(event) => setAccountIds(Array.from(event.target.selectedOptions).map((option) => option.value))}
                  className="h-24 w-full rounded-xl border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200 outline-none focus:border-cyan-500"
                >
                  {(accounts.data?.items ?? []).map((account) => (
                    <option key={account.id} value={account.id}>
                      {accountLabel(account)}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-slate-500">按住 Ctrl / ⌘ 多选。账号范围对本地语义检索生效，LLM 流程按平台分析全部候选。</p>
              </div>
            </div>
          </Panel>

          {/* right: dates + candidates + name + submit */}
          <Panel className="flex flex-col p-5">
            <div className="mb-5 flex items-start gap-3">
              <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-cyan-400/10 text-cyan-300">
                <SlidersHorizontal size={19} />
              </div>
              <div>
                <h2 className="font-semibold text-white">检索范围与计划</h2>
                <p className="mt-1 text-xs leading-5 text-slate-500">设置时间窗口、候选规模，以及可选的计划名称。</p>
              </div>
            </div>

            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="min-w-0">
                  <span className="mb-1.5 flex items-center gap-1.5 text-xs text-slate-400">
                    <Calendar size={12} /> 发布时间（起）
                  </span>
                  <input type="date" className={`${inputClass} w-full`} value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
                </label>
                <label className="min-w-0">
                  <span className="mb-1.5 flex items-center gap-1.5 text-xs text-slate-400">
                    <Calendar size={12} /> 发布时间（止）
                  </span>
                  <input type="date" className={`${inputClass} w-full`} value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
                </label>
              </div>

              <label className="block">
                <span className="mb-1.5 flex items-center gap-1.5 text-xs text-slate-400">
                  <SlidersHorizontal size={12} /> 候选数
                </span>
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={candidates}
                  onChange={(event) => setCandidates(Math.max(1, Math.min(200, Number(event.target.value) || 1)))}
                  className={`${inputClass} w-full`}
                />
              </label>

              <label className="block">
                <span className="mb-1.5 block text-xs text-slate-400">计划名称（可选）</span>
                <input className={`${inputClass} w-full`} value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：雨中冲刺素材" />
              </label>

              <div className="mt-auto rounded-xl border border-slate-800 bg-slate-950/40 p-3 text-xs leading-5 text-slate-400">
                创建计划后无需切换页面：下方可直接用 <span className="text-cyan-300">LLM 智能分析</span> 或{" "}
                <span className="text-cyan-300">本地语义检索</span> 执行同一份计划，结果在更下方合并展示。
              </div>

              <button type="button" className={`${buttonClass} w-full`} onClick={() => void createPlan()} disabled={submitting}>
                <Plus size={16} />
                {submitting ? "创建中…" : "创建内容搜索计划"}
              </button>
            </div>
          </Panel>
        </section>

      {/* ====================================================================== */}
      {/*  SECTION 2 — engine tabs (each runs its own flow)                     */}
      {/* ====================================================================== */}
      <div ref={section2Ref} className="space-y-6 scroll-mt-24">
          {/* engine TAB nav */}
          <div className="flex gap-2 rounded-xl border border-slate-800 bg-slate-950/40 p-1">
            <EngineTabButton active={engineTab === "llm"} onClick={() => setEngineTab("llm")} icon={<Sparkles size={15} />} label="LLM 智能分析" />
            <EngineTabButton active={engineTab === "local"} onClick={() => setEngineTab("local")} icon={<Database size={15} />} label="本地语义检索" />
          </div>

          {engineTab === "llm" ? (
            <LLMEngineTab
              plan={plan}
              plans={plans.data?.items ?? []}
              runsByPlan={latestRunByPlan}
              onRun={runPlan}
              onStop={stopPlan}
            />
          ) : (
            <LocalEngineTab
              mode={mode}
              setMode={setMode}
              chunkKinds={chunkKinds}
              setChunkKinds={setChunkKinds}
              limit={limit}
              setLimit={setLimit}
              status={status.data}
              disabled={disabled}
              searching={searching}
              onSearch={runLocalSearch}
            />
          )}
        </div>

      {/* ====================================================================== */}
      {/*  SECTION 3 — merged results (unified across both engines)             */}
      {/* ====================================================================== */}
      <div ref={section3Ref} className="scroll-mt-24">
        <Panel>
          <div className="flex flex-col gap-3 border-b border-slate-800 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-semibold text-white">合并结果</h2>
              <p className="mt-1 text-xs text-slate-500">
                LLM 与本地检索的结果统一展示 · 共 {unifiedResults.length} 条（LLM {llmCount} · 本地 {localCount}）
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {(["all", "llm", "local"] as ResultFilter[]).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setResultFilter(key)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                    resultFilter === key ? "bg-cyan-500/15 text-cyan-200" : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {key === "all" ? "全部" : key === "llm" ? "LLM" : "本地"}
                </button>
              ))}
              <span className="mx-1 h-5 w-px bg-slate-800" aria-hidden="true" />
              <button
                type="button"
                className={`${secondaryButtonClass} h-9 px-3 text-xs`}
                onClick={() => void runExport("md")}
                disabled={exporting !== null || filteredResults.length === 0}
                title="导出当前结果为 Markdown 简报"
              >
                <FileDown size={14} />
                {exporting === "md" ? "生成中…" : "下载 .md"}
              </button>
              <button
                type="button"
                className={`${secondaryButtonClass} h-9 px-3 text-xs`}
                onClick={() => void runExport("pdf")}
                disabled={exporting !== null || filteredResults.length === 0}
                title="通过浏览器打印视图另存为 PDF"
              >
                <Printer size={14} />
                {exporting === "pdf" ? "生成中…" : "下载 .pdf"}
              </button>
            </div>
          </div>

          {summaryQuery.isLoading ? (
            <div className="px-5 pb-1 pt-1 text-xs text-slate-500">正在生成智能摘要…</div>
          ) : summaryQuery.data ? (
            <SummaryCard summary={summaryQuery.data} />
          ) : null}

          {filteredResults.length === 0 ? (
            <StatePanel
              type="empty"
              title="还没有结果"
              detail="在上方 TAB 中运行 LLM 分析或执行本地检索，命中结果会合并显示在这里。"
            />
          ) : (
            <div className="grid gap-4 p-5 lg:grid-cols-2">
              {filteredResults.map((item) => (
                <UnifiedResultCard
                  key={`${item.engine}-${item.id}`}
                  result={item}
                  sentiment={summaryById.get(item.id)?.sentiment}
                  heat={summaryById.get(item.id)?.heat}
                  creatingTopic={creatingTopicId === item.candidateId}
                  onCreateTopic={item.candidateId ? () => void createTopicFromCandidate(item.candidateId!) : undefined}
                />
              ))}
            </div>
          )}
        </Panel>
      </div>
    </main>
  );
}

/* ========================================================================== */
/*  Tab / result primitives                                                    */
/* ========================================================================== */

function EngineTabButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: ReactNode; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition ${
        active ? "bg-cyan-500/15 text-cyan-200" : "text-slate-400 hover:text-slate-200"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

/* ========================================================================== */
/*  Step 2 — LLM engine tab                                                    */
/* ========================================================================== */

function LLMEngineTab({
  plan,
  plans,
  runsByPlan,
  onRun,
  onStop,
}: {
  plan: LLMPlan | null;
  plans: LLMPlan[];
  runsByPlan: Map<string, LLMRun>;
  onRun: (id: string) => void;
  onStop: (id: string) => void;
}) {
  const list = plan ? [plan, ...plans.filter((p) => p.id !== plan.id)] : plans;
  return (
    <Panel className="p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-white">LLM 智能分析</h2>
          <p className="mt-1 text-xs text-slate-500">读画面 / 语音 / OCR 给出内容证据，结果进入下方合并结果。</p>
        </div>
        <Sparkles size={19} className="text-cyan-400" />
      </div>

      {list.length === 0 ? (
        <StatePanel type="empty" title="还没有搜索计划" detail="返回第一步创建内容搜索计划。" />
      ) : (
        <div className="divide-y divide-slate-800/70">
          {list.map((p) => {
            const run = runsByPlan.get(p.id);
            const running = run && ["queued", "running", "stopping"].includes(run.status);
            return (
              <div key={p.id} className="grid gap-4 py-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="truncate font-medium text-slate-100" title={p.name}>{p.name}</h3>
                    <Badge tone={llmTone(p.status)}>{LLM_STATUS_LABELS[p.status] ?? p.status}</Badge>
                  </div>
                  <p className="mt-1 truncate text-sm text-slate-300" title={p.query_text}>{p.query_text}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>{p.platforms.map((item) => PLATFORM_KEYS.find((entry) => entry.key === item)?.label ?? item).join(" · ")}</span>
                    <span>·</span>
                    <span>{formatInterval(p.interval_seconds)}</span>
                    <span>·</span>
                    <span>阈值 {Math.round(p.min_match_score * 100)}%</span>
                    {run && (
                      <>
                        <span>·</span>
                        <span>本次 {run.analyzed_count}/{run.candidate_count} 已分析，命中 {run.matched_count}</span>
                      </>
                    )}
                  </div>
                  {p.last_error && <p className="mt-2 line-clamp-2 text-xs text-amber-300">来源提示：{p.last_error}</p>}
                </div>
                <div className="flex shrink-0 flex-wrap gap-2 lg:justify-end">
                  {running ? (
                    <button type="button" className={secondaryButtonClass} onClick={() => onStop(p.id)}>
                      <CircleStop size={15} /> 停止
                    </button>
                  ) : (
                    <button type="button" className={secondaryButtonClass} onClick={() => onRun(p.id)}>
                      <Play size={15} /> 立即运行
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

/* ========================================================================== */
/*  Step 2 — Local engine tab                                                  */
/* ========================================================================== */

function LocalEngineTab({
  mode,
  setMode,
  chunkKinds,
  setChunkKinds,
  limit,
  setLimit,
  status,
  disabled,
  searching,
  onSearch,
}: {
  mode: SearchMode;
  setMode: (mode: SearchMode) => void;
  chunkKinds: ChunkKind[];
  setChunkKinds: (kinds: ChunkKind[]) => void;
  limit: number;
  setLimit: (limit: number) => void;
  status: StatusResponse | undefined;
  disabled: boolean;
  searching: boolean;
  onSearch: () => void;
}) {
  const toggleKind = (kind: ChunkKind) =>
    setChunkKinds(chunkKinds.includes(kind) ? chunkKinds.filter((k) => k !== kind) : [...chunkKinds, kind]);

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)]">
      <Panel className="p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-white">本地语义检索</h2>
            <p className="mt-1 text-xs text-slate-500">对计划内的视频内容做即时混合召回，不调用 LLM。</p>
          </div>
          <Database size={19} className="text-cyan-400" />
        </div>

        <div className="space-y-4">
          <div>
            <span className="mb-1.5 block text-xs text-slate-400">检索模式</span>
            <div className="flex gap-2">
              {MODE_OPTIONS.map((option) => {
                const active = mode === option.key;
                return (
                  <button
                    type="button"
                    key={option.key}
                    title={option.hint}
                    onClick={() => setMode(option.key)}
                    className={`flex-1 rounded-xl border px-3 py-2 text-sm transition ${
                      active ? "border-cyan-500/70 bg-cyan-500/10 text-cyan-200" : "border-slate-800 bg-slate-950/40 text-slate-400 hover:border-slate-700"
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            <p className="mt-1.5 text-xs text-slate-500">{MODE_OPTIONS.find((option) => option.key === mode)?.hint}</p>
          </div>

          <div>
            <span className="mb-1.5 block text-xs text-slate-400">内容维度（不选 = 全部）</span>
            <div className="flex flex-wrap gap-2">
              {(Object.keys(CHUNK_KIND_LABELS) as ChunkKind[]).map((kind) => {
                const active = chunkKinds.includes(kind);
                const count = status?.chunk_kinds?.[kind];
                return (
                  <button
                    type="button"
                    key={kind}
                    onClick={() => toggleKind(kind)}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-sm transition ${
                      active ? "border-cyan-500/70 bg-cyan-500/10 text-cyan-200" : "border-slate-800 bg-slate-950/40 text-slate-500 hover:border-slate-700"
                    }`}
                  >
                    <Layers size={14} />
                    <span>{CHUNK_KIND_LABELS[kind]}</span>
                    {typeof count === "number" && <span className="text-[10px] text-slate-500">· {formatNumber(count)}</span>}
                  </button>
                );
              })}
            </div>
          </div>

          <label className="block">
            <span className="mb-1.5 block text-xs text-slate-400">返回条数</span>
            <input
              type="number"
              min={1}
              max={100}
              value={limit}
              onChange={(event) => setLimit(Math.max(1, Math.min(100, Number(event.target.value) || 1)))}
              className={`${inputClass} w-full`}
            />
          </label>

          <div className="flex items-center gap-2">
            <button type="button" className={`${buttonClass} flex-1`} onClick={onSearch} disabled={searching || disabled}>
              <Search size={16} />
              {searching ? "检索中…" : "执行本地检索"}
            </button>
            {disabled && <span className="text-xs text-amber-300">检索服务未启用</span>}
          </div>
          <p className="text-xs text-slate-500">将使用第一步计划中的内容描述、平台、账号与时间范围作为检索条件。</p>
        </div>
      </Panel>

      <Panel className="p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-white">索引状态</h2>
            <p className="mt-1 text-xs text-slate-500">向量索引健康度（管理见「设置 → 语义检索」）。</p>
          </div>
          <Database size={19} className="text-cyan-400" />
        </div>

        {status == null ? (
          <div className="p-6 text-sm text-slate-500">加载索引状态…</div>
        ) : disabled ? (
          <StatePanel
            type="empty"
            title="本地检索未启用"
            detail="服务端未配置 embedding 后端（SIO_EMBEDDING_BACKEND）。配置后此处会显示索引状态，索引管理在「设置 → 语义检索」。"
          />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <Stat label="已索引内容" value={formatNumber(status.embedded_items ?? 0)} />
              <Stat label="已索引块" value={formatNumber(status.embedded_chunks ?? 0)} />
              <Stat label="待索引" value={formatNumber(status.pending_items ?? 0)} tone={(status.pending_items ?? 0) > 0 ? "warning" : "default"} />
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-xs leading-5 text-slate-400">
              <div className="flex items-center justify-between gap-3">
                <span>新鲜度</span>
                <Badge tone={status.freshness === "fresh" ? "success" : status.freshness === "stale" ? "warning" : "neutral"}>
                  {status.freshness === "fresh" ? "最新" : status.freshness === "stale" ? "待补索引" : "暂无索引"}
                </Badge>
              </div>
              <p className="mt-1">{status.freshness_detail}</p>
              <p className="mt-1 text-slate-500">
                最近索引：{status.latest_embedded_at ? new Date(status.latest_embedded_at).toLocaleString("zh-CN") : "—"}
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-xs leading-5 text-slate-400">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Network size={13} className="text-cyan-400" /> 后端
                </span>
                <span className="text-slate-200">{status.backend}</span>
              </div>
              <div className="mt-1 flex items-center justify-between">
                <span>模型</span>
                <span className="text-slate-200">{status.model ?? "—"}</span>
              </div>
              <div className="mt-1 flex items-center justify-between">
                <span>向量维度</span>
                <span className="text-slate-200">{status.dimension ?? "—"}</span>
              </div>
            </div>
            <a className={`${secondaryButtonClass} w-full justify-center`} href="/settings?tab=search">
              <Settings2 size={15} /> 前往「设置 → 语义检索」管理索引
            </a>
          </div>
        )}
      </Panel>
    </div>
  );
}

/* ========================================================================== */
/*  Unified result card                                                        */
/* ========================================================================== */

function UnifiedResultCard({
  result,
  sentiment,
  heat,
  creatingTopic,
  onCreateTopic,
}: {
  result: UnifiedResult;
  sentiment?: "positive" | "neutral" | "negative";
  heat?: number;
  creatingTopic: boolean;
  onCreateTopic?: () => void;
}) {
  return (
    <article className="flex gap-4 rounded-xl border border-slate-800 bg-slate-950/40 p-4">
      {result.cover_url ? (
        <a href={result.url} target="_blank" rel="noreferrer" className="block h-20 w-32 shrink-0 overflow-hidden rounded-lg bg-slate-900">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={result.cover_url} alt={result.title} className="size-full object-cover" loading="lazy" />
        </a>
      ) : (
        <div className="grid h-20 w-32 shrink-0 place-items-center rounded-lg bg-slate-900 text-slate-600">
          <Video size={20} />
        </div>
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <a
            href={result.url}
            target="_blank"
            rel="noreferrer"
            className="line-clamp-2 text-sm font-medium text-slate-100 hover:text-cyan-300"
            title={result.title}
          >
            {result.title || "无标题"}
          </a>
          <span className="flex shrink-0 items-center gap-1.5">
            <EngineBadge engine={result.engine} />
            <span className="text-xs tabular-nums text-cyan-300">{result.scoreText}</span>
          </span>
        </div>

        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <Badge tone="info">{result.platformLabel}</Badge>
          <span className="text-xs text-slate-500">{result.accountLabel}</span>
        </div>

        <p className="mt-1 text-xs text-slate-500">{result.meta}</p>

        <div className="mt-2 flex flex-wrap gap-1.5">
          {result.badges.map((badge, index) => (
            <Badge key={index} tone={badge.tone}>{badge.label}</Badge>
          ))}
        </div>

        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {sentiment && (
            <Badge tone={sentiment === "positive" ? "success" : sentiment === "negative" ? "danger" : "neutral"}>
              {sentiment === "positive" ? "正面" : sentiment === "negative" ? "负面" : "中性"}
            </Badge>
          )}
          {heat != null && <Badge tone="warning">热度 {Math.round(heat * 100)}%</Badge>}
        </div>

        {result.snippet && (
          <p className="mt-2 text-xs leading-5 text-slate-300">{result.snippet}</p>
        )}

        {result.evidenceWindow && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <a
              href={evidenceLocatorUrl(result.url, result.evidenceWindow.startMs)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-1.5 text-cyan-200 hover:bg-cyan-500/20"
            >
              <Play size={12} />
              定位时间证据 {formatEvidenceTime(result.evidenceWindow.startMs)}–{formatEvidenceTime(result.evidenceWindow.endMs)}
            </a>
            <span className="text-slate-500">
              {result.evidenceWindow.label}
              {result.evidenceWindow.sourceRef ? ` · ${result.evidenceWindow.sourceRef}` : ""}
            </span>
          </div>
        )}

        {onCreateTopic && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={`${secondaryButtonClass} h-8 px-2.5 text-xs`}
              onClick={onCreateTopic}
              disabled={creatingTopic}
            >
              <Plus size={13} />
              {creatingTopic ? "加入中…" : "加入选题库"}
            </button>
            <span className="text-[11px] text-slate-600">保留原视频 URL、抓取时间和内容证据</span>
          </div>
        )}
      </div>
    </article>
  );
}

function SummaryCard({ summary }: { summary: SummaryResponse }) {
  const entries = Object.entries(summary.platform_distribution);
  return (
    <div className="border-b border-slate-800 px-5 py-4">
      <div className="flex items-center gap-2">
        <Sparkles size={14} className="text-cyan-300" />
        <h3 className="text-sm font-semibold text-white">智能摘要</h3>
        <span className="text-xs text-slate-500">共 {summary.total} 条</span>
      </div>
      {summary.llm_summary ? (
        <p className="mt-2 text-xs leading-5 text-slate-300">{summary.llm_summary}</p>
      ) : (
        <p className="mt-2 text-xs leading-5 text-slate-400">
          覆盖平台 {entries.length} 个 · LLM {summary.engine_distribution.llm ?? 0} 条、本地 {summary.engine_distribution.local ?? 0} 条。各卡片标签给出情感倾向与热度（按相关度估算，接入播放/互动统计后将更精准）。
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {entries.map(([platform, count]) => (
          <span key={platform} className="inline-flex items-center gap-1 rounded-full bg-slate-800/60 px-2.5 py-1 text-xs text-slate-300">
            {platform} <span className="text-cyan-300">{count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function EngineBadge({ engine }: { engine: Engine }) {
  if (engine === "llm") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] font-medium text-violet-200">
        <Sparkles size={10} /> LLM
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-cyan-500/15 px-2 py-0.5 text-[10px] font-medium text-cyan-200">
      <Database size={10} /> 本地
    </span>
  );
}

function Stat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "warning";
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3 text-center">
      <p className={`text-lg font-semibold tabular-nums ${tone === "warning" ? "text-amber-300" : "text-white"}`}>{value}</p>
      <p className="mt-1 text-xs text-slate-500">{label}</p>
    </div>
  );
}
