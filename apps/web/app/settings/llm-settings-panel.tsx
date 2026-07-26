"use client";

import type {
  LLMProviderSettingRecord,
  LLMProviderTestResult,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Save, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";

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
};

const EMPTY_FORM: LLMForm = {
  name: "OpenAI 兼容接口",
  base_url: "https://api.openai.com/v1",
  api_key: "",
  clear_api_key: false,
  organization: "",
  project: "",
  custom_headers: "",
  default_model: "gpt-4.1-mini",
  temperature: 0.4,
  top_p: 1,
  max_tokens: 4096,
  timeout_seconds: 60,
  max_attempts: 3,
  input_cost_per_million: "",
  output_cost_per_million: "",
  enabled: true,
};

function numberValue(value: unknown, fallback: number): number {
  if (typeof value !== "number" && typeof value !== "string") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formFromRecord(value: LLMProviderSettingRecord | undefined): LLMForm {
  if (!value) return EMPTY_FORM;
  const config = value.config_masked;
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
    max_tokens: numberValue(value.default_parameters.max_tokens, 4096),
    timeout_seconds: numberValue(
      config.timeout_seconds ?? value.default_parameters.timeout_seconds,
      60,
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
  };
}

export function LLMSettingsPanel() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [formOverrides, setFormOverrides] = useState<Partial<LLMForm>>({});
  const [busy, setBusy] = useState(false);
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
  const canAdmin = ["owner", "admin"].includes(role ?? "");

  const form = useMemo(
    () => ({ ...formFromRecord(setting.data), ...formOverrides }),
    [formOverrides, setting.data],
  );

  function update<K extends keyof LLMForm>(key: K, value: LLMForm[K]) {
    setFormOverrides((current) => ({ ...current, [key]: value }));
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
    };
  }

  async function save() {
    if (!workspaceId) return;
    setBusy(true);
    try {
      await apiRequest<LLMProviderSettingRecord>(
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
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-medium text-white">OpenAI 兼容 Provider</h2>
              <Badge tone={record?.configured ? "success" : "warning"}>
                {record?.configured ? "已配置" : "尚未可用"}
              </Badge>
              <Badge tone="neutral">来源：{record?.source ?? "unknown"}</Badge>
            </div>
            <p className="mt-2 max-w-3xl text-xs leading-5 text-slate-500">
              适用于 OpenAI、OpenRouter、DeepSeek 与其他兼容 Chat Completions
              的公网接口。API Key
              只在后端加密保存，日志和响应均不返回明文；私网地址会被 SSRF
              防护拒绝。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className={secondaryButtonClass}
              disabled={busy || !canAdmin || !record?.configured}
              onClick={testConnection}
              type="button"
            >
              <FlaskConical size={14} />
              测试连接
            </button>
            <button
              className={buttonClass}
              disabled={busy || !canAdmin}
              onClick={save}
              type="button"
            >
              <Save size={14} />
              保存配置
            </button>
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
        <div className="grid gap-5 lg:grid-cols-2">
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
          <TextField
            label="默认模型"
            value={form.default_model}
            onChange={(value) => update("default_model", value)}
          />
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
