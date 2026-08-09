"use client";

import type {
  LLMModelsResult,
  LLMProviderSettingRecord,
  LLMProviderTestResult,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FlaskConical,
  Loader2,
  RefreshCw,
  Save,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  Panel,
  SkeletonRows,
  StatePanel,
  SettingsGroup,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";

type LLMCallMode = "api" | "browser_proxy";

type LLMForm = {
  name: string;
  base_url: string;
  api_key: string;
  clear_api_key: boolean;
  organization: string;
  project: string;
  custom_headers: string;
  default_model: string;
  temperature: number;
  top_p: number;
  max_tokens: number;
  timeout_seconds: number;
  max_attempts: number;
  input_cost_per_million: string;
  output_cost_per_million: string;
  enabled: boolean;
  call_mode: LLMCallMode;
};

const EMPTY_FORM: LLMForm = {
  name: "OpenAI 兼容接口",
  base_url: "https://api.openai.com/v1",
  api_key: "",
  clear_api_key: false,
  organization: "",
  project: "",
  custom_headers: "",
  default_model: "gpt-5.6-terra",
  temperature: 0.4,
  top_p: 1,
  max_tokens: 8192,
  timeout_seconds: 90,
  max_attempts: 3,
  input_cost_per_million: "",
  output_cost_per_million: "",
  enabled: true,
  call_mode: "api",
};

function numberValue(value: unknown, fallback: number): number {
  if (typeof value !== "number" && typeof value !== "string") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formFromRecord(value: LLMProviderSettingRecord | undefined): LLMForm {
  if (!value) return EMPTY_FORM;
  const config = value.config_masked;
  const savedCallMode =
    typeof config.call_mode === "string" && config.call_mode === "browser_proxy"
      ? "browser_proxy"
      : value.base_url === "http://llm-experimental:8080/v1"
        ? "browser_proxy"
        : "api";
  return {
    name: value.name,
    base_url: value.base_url ?? "https://api.openai.com/v1",
    api_key: "",
    clear_api_key: false,
    organization:
      typeof config.organization === "string" ? config.organization : "",
    project: typeof config.project === "string" ? config.project : "",
    custom_headers: "",
    default_model: value.default_model,
    temperature: numberValue(value.default_parameters.temperature, 0.4),
    top_p: numberValue(value.default_parameters.top_p, 1),
    max_tokens: numberValue(value.default_parameters.max_tokens, 8192),
    timeout_seconds: numberValue(
      config.timeout_seconds ?? value.default_parameters.timeout_seconds,
      90,
    ),
    max_attempts: numberValue(
      config.max_attempts ?? value.default_parameters.max_attempts,
      3,
    ),
    input_cost_per_million:
      value.input_cost_per_million === null
        ? ""
        : String(value.input_cost_per_million),
    output_cost_per_million:
      value.output_cost_per_million === null
        ? ""
        : String(value.output_cost_per_million),
    enabled: value.enabled,
    call_mode: savedCallMode as LLMCallMode,
  };
}

const LLM_PRESETS: Array<{
  key: string;
  label: string;
  base_url: string;
  default_model: string;
}> = [
  // ─── 国际主流 ───────────────────────────────────────────────────────
  {
    key: "openai",
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    default_model: "gpt-5.6-terra",
  },
  {
    key: "anthropic",
    label: "Anthropic (Claude)",
    base_url: "https://api.anthropic.com/v1",
    default_model: "claude-sonnet-5",
  },
  {
    key: "gemini",
    label: "Google Gemini",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
    default_model: "gemini-3.5-flash",
  },
  {
    key: "mistral",
    label: "Mistral AI",
    base_url: "https://api.mistral.ai/v1",
    default_model: "mistral-medium-3.5",
  },
  {
    key: "grok",
    label: "Grok (xAI)",
    base_url: "https://api.x.ai/v1",
    default_model: "grok-4.5",
  },
  {
    key: "groq-lpu",
    label: "Groq (LPU)",
    base_url: "https://api.groq.com/openai/v1",
    default_model: "openai/gpt-oss-120b",
  },
  {
    key: "openrouter",
    label: "OpenRouter",
    base_url: "https://openrouter.ai/api/v1",
    default_model: "openai/gpt-5.6-terra",
  },
  {
    key: "together",
    label: "Together AI",
    base_url: "https://api.together.xyz/v1",
    default_model: "thinkingmachines/Inkling",
  },
  {
    key: "perplexity",
    label: "Perplexity",
    base_url: "https://api.perplexity.ai",
    default_model: "sonar",
  },
  {
    key: "cohere",
    label: "Cohere",
    base_url: "https://api.cohere.ai/compatibility/v1",
    default_model: "command-a-03-2025",
  },
  {
    key: "bedrock",
    label: "AWS Bedrock (OpenAI 兼容)",
    base_url:
      "https://bedrock-runtime.us-east-1.amazonaws.com/model/anthropic.claude-3-5-sonnet-20241022-v2:0/converse",
    default_model: "anthropic.claude-sonnet-5",
  },
  // ─── 国内主流 ───────────────────────────────────────────────────────
  {
    key: "deepseek",
    label: "DeepSeek",
    base_url: "https://api.deepseek.com/v1",
    default_model: "deepseek-chat",
  },
  {
    key: "moonshot",
    label: "Moonshot (Kimi)",
    base_url: "https://api.moonshot.cn/v1",
    default_model: "kimi-k3",
  },
  {
    key: "zhipu",
    label: "智谱 AI (GLM)",
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    default_model: "glm-5",
  },
  {
    key: "qwen",
    label: "通义千问 (Qwen)",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    default_model: "qwen3.8-max",
  },
  {
    key: "doubao",
    label: "豆包 (Doubao)",
    base_url: "https://ark.cn-beijing.volces.com/api/v3",
    default_model: "doubao-seed-1-8-251228",
  },
  {
    key: "spark",
    label: "讯飞星火 (Spark)",
    base_url: "https://spark-api-open.xf-yun.com/v1",
    default_model: "generalv3.5",
  },
  {
    key: "hunyuan",
    label: "腾讯混元 (Hunyuan)",
    base_url: "https://api.hunyuan.cloud.tencent.com/v1",
    default_model: "hunyuan-turbos",
  },
  {
    key: "wenxin",
    label: "百度文心 (ERNIE)",
    base_url: "https://qianfan.baidubce.com/v2",
    default_model: "ernie-4.5-turbo-32k",
  },
  {
    key: "minimax",
    label: "MiniMax",
    base_url: "https://api.minimax.chat/v1",
    default_model: "MiniMax-M2.7",
  },
  {
    key: "step",
    label: "阶跃星辰 (Step)",
    base_url: "https://api.stepfun.com/v1",
    default_model: "step-3.5-flash",
  },
  {
    key: "360",
    label: "360 智脑",
    base_url: "https://ai.360.cn/v1",
    default_model: "360GPT2-Pro",
  },
  // ─── 本地 / 网关 ───────────────────────────────────────────────────
  {
    key: "ollama",
    label: "Ollama（本地）",
    base_url: "http://localhost:11434/v1",
    default_model: "qwen3.5:9b",
  },
  {
    key: "new-api",
    label: "New API 网关（本地）",
    base_url: "http://llm-gateway:3000/v1",
    default_model: "gpt-5.6-terra",
  },
  {
    key: "chat2api",
    label: "Chat2API 实验（本地）",
    base_url: "http://llm-experimental:8080/v1",
    default_model: "gpt-5.6-terra",
  },
];

const MODEL_CATALOGS: Record<string, string[]> = {
  // 预制项是脱离 API Key 时的安全基线；保存配置后会以 Provider /models
  // 实时清单覆盖它们。模型 ID 按 2026-08-06 官方目录复核。
  openai: ["gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-4.1-mini"],
  anthropic: ["claude-fable-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
  gemini: ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"],
  mistral: ["mistral-medium-3.5", "mistral-small-4", "mistral-large-3"],
  grok: ["grok-4.5", "grok-4", "grok-3-mini"],
  "groq-lpu": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "groq/compound", "groq/compound-mini"],
  openrouter: ["openai/gpt-5.6-terra", "anthropic/claude-opus-5", "google/gemini-3.6-flash", "deepseek/deepseek-chat", "openai/gpt-4.1-mini"],
  together: ["thinkingmachines/Inkling", "MiniMaxAI/MiniMax-M3", "Qwen/Qwen3.7-Max", "moonshotai/Kimi-K3", "zai-org/GLM-5.2", "openai/gpt-oss-120b"],
  perplexity: ["sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"],
  cohere: ["command-a-03-2025", "command-r-plus-08-2024", "command-r7b-12-2024"],
  bedrock: ["anthropic.claude-fable-5", "anthropic.claude-opus-5", "anthropic.claude-sonnet-5", "anthropic.claude-haiku-4-5"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
  moonshot: ["kimi-k3", "kimi-k2.7-code-highspeed", "kimi-k2.6", "kimi-k2.5"],
  zhipu: ["glm-5", "glm-4.7", "glm-4.5"],
  qwen: ["qwen3.8-max", "qwen3.7-plus", "qwen3.7-flash", "qwen3-max", "qwen-plus"],
  doubao: ["doubao-seed-1-8-251228", "doubao-seed-1-6-251015", "doubao-1-5-pro-32k-250115"],
  spark: ["generalv3.5", "generalv3.5-16k", "general4v"],
  hunyuan: ["hunyuan-turbos", "hunyuan-pro", "hunyuan-large"],
  wenxin: ["ernie-4.5-turbo-32k", "ernie-5.0-thinking-preview", "ernie-4.0-turbo-8k"],
  minimax: ["MiniMax-M2.7", "MiniMax-M2.5", "MiniMax-01"],
  step: ["step-3.5-flash", "step-3.5", "step-2-16k"],
  360: ["360GPT2-Pro", "360GPT2-Pro-32K"],
  ollama: ["qwen3.5:9b", "qwen3:8b", "llama3.3", "deepseek-r1:8b"],
  "new-api": ["gpt-5.6-terra", "claude-sonnet-5", "gemini-3.5-flash", "gpt-4.1-mini"],
  chat2api: ["gpt-5.6-terra", "claude-sonnet-5", "gemini-3.5-flash"],
};

/** Detect which preset matches a saved base_url (by hostname). */
function detectPresetKey(baseUrl: string | undefined): string {
  if (!baseUrl) return "openai";
  const normalized = baseUrl.replace(/\/+$/, "").toLowerCase();
  for (const preset of LLM_PRESETS) {
    const presetNormalized = preset.base_url.replace(/\/+$/, "").toLowerCase();
    if (
      normalized === presetNormalized ||
      normalized.startsWith(presetNormalized.replace(/\/v\d+.*$/, ""))
    ) {
      return preset.key;
    }
  }
  // Fallback: match by hostname
  try {
    const host = new URL(baseUrl).hostname.toLowerCase();
    for (const preset of LLM_PRESETS) {
      if (preset.base_url.toLowerCase().includes(host)) return preset.key;
    }
  } catch {
    /* ignore invalid URLs */
  }
  return "openai";
}

export function LLMSettingsPanel() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [formOverrides, setFormOverrides] = useState<Partial<LLMForm>>({});
  const [busy, setBusy] = useState(false);
  const [selectedPreset, setSelectedPreset] = useState("openai");
  const [testResult, setTestResult] = useState<LLMProviderTestResult | null>(
    null,
  );
  const setting = useQuery({
    queryKey: ["llm-setting", workspaceId],
    queryFn: () =>
      apiRequest<LLMProviderSettingRecord>("/settings/llm/openai-compatible", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const modelCatalog = useQuery({
    queryKey: ["llm-models", workspaceId],
    queryFn: () =>
      apiRequest<LLMModelsResult>("/settings/llm/models", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && Boolean(setting.data?.configured),
    staleTime: 60_000,
  });
  const canAdmin = ["owner", "admin"].includes(role ?? "");
  const presetDetected = useRef(false);

  // Auto-detect the matching preset from the saved base_url on first load
  useEffect(() => {
    if (presetDetected.current || !setting.data) return;
    presetDetected.current = true;
    const savedUrl = setting.data.base_url;
    if (savedUrl) {
      // One-time preset detection from saved base_url; guarded by a ref.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedPreset(detectPresetKey(savedUrl));
    }
  }, [setting.data]);

  const form = useMemo(
    () => ({ ...formFromRecord(setting.data), ...formOverrides }),
    [formOverrides, setting.data],
  );
  const modelOptions = useMemo(() => {
    const live = modelCatalog.data?.items ?? [];
    if (live.length) return live.map((item) => ({ id: item.id, name: item.name }));
    const preset = LLM_PRESETS.find((item) => item.key === selectedPreset);
    const ids = MODEL_CATALOGS[selectedPreset] ?? (preset ? [preset.default_model] : []);
    return ids.map((id) => ({ id, name: id }));
  }, [modelCatalog.data?.items, selectedPreset]);

  function update<K extends keyof LLMForm>(key: K, value: LLMForm[K]) {
    setFormOverrides((current) => ({ ...current, [key]: value }));
  }

  function applyPreset(presetKey: string) {
    setSelectedPreset(presetKey);
    const preset = LLM_PRESETS.find((p) => p.key === presetKey);
    if (preset) {
      setFormOverrides((current) => ({
        ...current,
        name: preset.label,
        base_url: preset.base_url,
        default_model: preset.default_model,
        call_mode: "api",
      }));
    }
  }

  function handleCallModeChange(mode: LLMCallMode) {
    if (mode === "browser_proxy") {
      setFormOverrides((current) => ({
        ...current,
        call_mode: "browser_proxy",
        base_url: "http://llm-experimental:8080/v1",
      }));
    } else {
      setFormOverrides((current) => ({
        ...current,
        call_mode: "api",
      }));
    }
  }

  function buildPayload() {
    let customHeaders: Record<string, string> | undefined;
    if (form.custom_headers.trim()) {
      const parsed: unknown = JSON.parse(form.custom_headers);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("自定义请求头必须是 JSON 对象。");
      }
      customHeaders = Object.fromEntries(
        Object.entries(parsed).map(([key, value]) => [key, String(value)]),
      );
    }
    return {
      name: form.name,
      base_url: form.base_url,
      ...(form.api_key ? { api_key: form.api_key } : {}),
      clear_api_key: form.clear_api_key,
      organization: form.organization || null,
      project: form.project || null,
      ...(customHeaders === undefined ? {} : { custom_headers: customHeaders }),
      default_model: form.default_model,
      temperature: form.temperature,
      top_p: form.top_p,
      max_tokens: form.max_tokens,
      timeout_seconds: form.timeout_seconds,
      max_attempts: form.max_attempts,
      input_cost_per_million: form.input_cost_per_million || null,
      output_cost_per_million: form.output_cost_per_million || null,
      enabled: form.enabled,
      call_mode: form.call_mode,
    };
  }

  async function save() {
    if (!workspaceId) return;
    setBusy(true);
    try {
      const updated = await apiRequest<LLMProviderSettingRecord>(
        "/settings/llm/openai-compatible",
        {
          method: "PUT",
          workspaceId,
          csrf: true,
          body: JSON.stringify(buildPayload()),
        },
      );
      notify("LLM 配置已加密保存，并将用于新的生成任务。", "success");
      setFormOverrides({});
      setTestResult(null);
      // Immediately update cache with the fresh response so the UI reflects
      // the saved state (configured: true, correct name) without waiting for refetch.
      queryClient.setQueryData(["llm-setting", workspaceId], updated);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["llm-setting"] }),
        queryClient.invalidateQueries({ queryKey: ["llm-providers"] }),
      ]);
    } catch (error) {
      notify(
        error instanceof Error ? error.message : "LLM 配置保存失败",
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  async function testConnection() {
    if (!workspaceId) return;
    if (
      !window.confirm(
        "将向当前 LLM Base URL 发起真实的模型列表请求，是否继续？",
      )
    )
      return;
    setBusy(true);
    try {
      const result = await apiRequest<LLMProviderTestResult>(
        "/settings/llm/openai-compatible/test",
        { method: "POST", workspaceId, csrf: true, body: JSON.stringify({}) },
      );
      setTestResult(result);
      notify(
        result.status === "ok" ? "LLM 连接测试成功" : result.detail,
        result.status === "ok" ? "success" : "error",
      );
      await queryClient.invalidateQueries({ queryKey: ["llm-setting"] });
    } catch (error) {
      notify(
        error instanceof Error ? error.message : "LLM 连接测试失败",
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  if (setting.isLoading) return <SkeletonRows count={6} />;
  if (setting.error) {
    return (
      <StatePanel
        type="error"
        title="无法读取 LLM 配置"
        detail={setting.error.message}
        onRetry={() => setting.refetch()}
      />
    );
  }

  const record = setting.data;
  return (
    <div className="space-y-5">
      <Panel className="p-5">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="font-medium text-white">LLM Provider 配置</h2>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                选择模型提供商，填写 API Key
                后即可用于内容生成。所有提供商均通过 OpenAI 兼容接口对接。
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                className={secondaryButtonClass}
                disabled={busy || !canAdmin || !record?.configured}
                onClick={testConnection}
                type="button"
              >
                {busy ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <FlaskConical size={14} />
                )}
                测试连接
              </button>
              <button
                className={buttonClass}
                disabled={busy || !canAdmin}
                onClick={save}
                type="button"
              >
                {busy ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Save size={14} />
                )}
                保存配置
              </button>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-sm font-medium text-slate-300">
              模型提供商
            </label>
            <select
              className={`${inputClass} max-w-xs`}
              onChange={(e) => applyPreset(e.target.value)}
              value={selectedPreset}
            >
              {LLM_PRESETS.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </select>
            <div className="flex items-center gap-2">
              <Badge tone={record?.configured ? "success" : "warning"}>
                {record?.configured ? "已配置" : "尚未可用"}
              </Badge>
            </div>
          </div>
        </div>
        {!canAdmin && (
          <p className="mt-4 text-xs text-amber-300">
            仅工作区 Owner/Admin 可以修改或测试配置。
          </p>
        )}
        {testResult && (
          <div className="mt-4 rounded-lg border border-slate-800 bg-slate-900/50 p-3 text-xs">
            <Badge tone={testResult.status === "ok" ? "success" : "danger"}>
              {testResult.status}
            </Badge>
            <span className="ml-3 text-slate-300">{testResult.detail}</span>
          </div>
        )}
      </Panel>

      <Panel className="p-5">
        <SettingsGroup
          title="调用方式"
          description="选择直接调用 Provider，或使用实验性的浏览器代理模式。"
          tone="violet"
        >
        <div className="flex flex-col gap-3">
          <label className="text-sm font-medium text-slate-300">调用方式</label>
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                checked={form.call_mode === "api"}
                className="accent-cyan-500"
                onChange={() => handleCallModeChange("api")}
                type="radio"
              />
              <span>API 直连（推荐，稳定可靠）</span>
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                checked={form.call_mode === "browser_proxy"}
                className="accent-cyan-500"
                onChange={() => handleCallModeChange("browser_proxy")}
                type="radio"
              />
              <span>浏览器代理（实验性，节约成本）</span>
              {form.call_mode === "browser_proxy" && (
                <Badge tone="warning">实验性</Badge>
              )}
            </label>
          </div>
          {form.call_mode === "browser_proxy" && (
            <p className="text-xs text-amber-300/80">
              浏览器代理模式将通过 Chat2API / g4f 服务模拟浏览器请求，Base URL
              已自动设为
              http://llm-experimental:8080/v1。该模式可能不稳定，仅建议在测试环境使用。
            </p>
          )}
        </div>
        </SettingsGroup>
      </Panel>

      <Panel className="p-5">
        <SettingsGroup
          title="连接、模型与生成参数"
          description="连接信息、可用模型、采样参数和成本参数统一在此维护。"
          tone="cyan"
        >
        <div className="grid gap-3 lg:grid-cols-2">
          <TextField
            label="配置名称"
            value={form.name}
            onChange={(value) => update("name", value)}
          />
          <TextField
            label="API Base URL"
            value={form.base_url}
            onChange={(value) => update("base_url", value)}
          />
          <TextField
            label={`API Key${record?.api_key_configured ? "（已保存；留空保持原值）" : ""}`}
            type="password"
            value={form.api_key}
            onChange={(value) => update("api_key", value)}
          />
          <div className="flex min-w-0 flex-col gap-1.5 text-sm text-slate-300">
            <div className="flex items-center justify-between gap-2">
              <label htmlFor="llm-default-model">默认模型</label>
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-[11px] text-slate-500">
                  {modelCatalog.data?.source === "live"
                    ? "当前 Provider 实时清单"
                    : "官方目录基线"}
                </span>
                <button
                  type="button"
                  className={`${secondaryButtonClass} h-8 shrink-0 px-2 text-xs`}
                  disabled={!record?.configured || modelCatalog.isFetching}
                  onClick={() => void modelCatalog.refetch()}
                  title={
                    record?.configured
                      ? "刷新当前 Provider 的 /models 清单"
                      : "保存并配置 API Key 后可刷新"
                  }
                >
                  <RefreshCw
                    size={13}
                    className={modelCatalog.isFetching ? "animate-spin" : undefined}
                  />
                  刷新
                </button>
              </div>
            </div>
            <select
              id="llm-default-model"
              aria-label="默认模型"
              className={inputClass}
              value={form.default_model}
              onChange={(event) => update("default_model", event.target.value)}
            >
              {!modelOptions.some((item) => item.id === form.default_model) && (
                <option value={form.default_model}>{form.default_model}（当前）</option>
              )}
              {modelOptions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] leading-4 text-slate-500">
              保存并配置 API Key 后，系统会从当前 Provider 的 <code>/models</code> 接口刷新可用模型；未配置时显示官方目录基线（2026-08-06）。
            </p>
          </div>
          <TextField
            label="Organization（可选）"
            value={form.organization}
            onChange={(value) => update("organization", value)}
          />
          <TextField
            label="Project（可选）"
            value={form.project}
            onChange={(value) => update("project", value)}
          />
          <NumberField
            label="Temperature"
            min={0}
            max={2}
            step={0.1}
            value={form.temperature}
            onChange={(value) => update("temperature", value)}
          />
          <NumberField
            label="Top P"
            min={0}
            max={1}
            step={0.05}
            value={form.top_p}
            onChange={(value) => update("top_p", value)}
          />
          <NumberField
            label="最大输出 Token"
            min={1}
            max={131072}
            step={1}
            value={form.max_tokens}
            onChange={(value) => update("max_tokens", value)}
          />
          <NumberField
            label="请求超时（秒）"
            min={5}
            max={300}
            step={1}
            value={form.timeout_seconds}
            onChange={(value) => update("timeout_seconds", value)}
          />
          <NumberField
            label="最大尝试次数"
            min={1}
            max={5}
            step={1}
            value={form.max_attempts}
            onChange={(value) => update("max_attempts", value)}
          />
          <TextField
            label="输入成本 / 百万 Token（可选）"
            type="number"
            value={form.input_cost_per_million}
            onChange={(value) => update("input_cost_per_million", value)}
          />
          <TextField
            label="输出成本 / 百万 Token（可选）"
            type="number"
            value={form.output_cost_per_million}
            onChange={(value) => update("output_cost_per_million", value)}
          />
          <label className="grid gap-2 text-sm lg:col-span-2">
            <span>自定义请求头（JSON；留空保持已保存值）</span>
            <textarea
              className={`${inputClass} h-24 py-2 font-mono`}
              onChange={(event) => update("custom_headers", event.target.value)}
              placeholder={'{"X-Tenant-ID":"example"}'}
              value={form.custom_headers}
            />
            <span className="text-xs text-slate-500">
              最多 20 项；Authorization、Host、Content-Length 不允许覆盖。输入{" "}
              {} 可清空。
            </span>
          </label>
        </div>
        </SettingsGroup>
        <div className="mt-5 flex flex-wrap gap-6 border-t border-slate-800 pt-5 text-sm">
          <label className="flex items-center gap-2">
            <input
              checked={form.enabled}
              onChange={(event) => update("enabled", event.target.checked)}
              type="checkbox"
            />
            启用此工作区配置
          </label>
          <label className="flex items-center gap-2 text-rose-300">
            <input
              checked={form.clear_api_key}
              onChange={(event) =>
                update("clear_api_key", event.target.checked)
              }
              type="checkbox"
            />
            清除已保存 API Key
          </label>
        </div>
      </Panel>

      <Panel className="p-5 text-sm">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 text-cyan-400" size={18} />
          <div>
            <h2 className="font-medium text-white">状态与生效范围</h2>
            <dl className="mt-3 grid grid-cols-[9rem_1fr] gap-y-2 text-xs">
              <dt className="text-slate-500">健康状态</dt>
              <dd>{record?.health_status ?? "unknown"}</dd>
              <dt className="text-slate-500">最近测试</dt>
              <dd>{formatDate(record?.last_tested_at)}</dd>
              <dt className="text-slate-500">最近更新</dt>
              <dd>{formatDate(record?.updated_at)}</dd>
              <dt className="text-slate-500">生效任务</dt>
              <dd>新的手动生成、Worker 生成与自动化 create_generation 动作</dd>
            </dl>
          </div>
        </div>
      </Panel>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "password" | "number";
}) {
  return (
    <label className="grid gap-2 text-sm">
      <span>{label}</span>
      <input
        className={inputClass}
        onChange={(event) => onChange(event.target.value)}
        type={type}
        value={value}
      />
    </label>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="grid gap-2 text-sm">
      <span>{label}</span>
      <input
        className={inputClass}
        max={max}
        min={min}
        onChange={(event) => onChange(Number(event.target.value))}
        step={step}
        type="number"
        value={value}
      />
    </label>
  );
}
