"use client";

import type {
  EditorialRuleSetSummary,
  GenerationWorkflow,
  LLMProviderDescriptor,
  ProblemDetails,
  PromptCollectionSummary,
} from "@sio/shared-types";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

async function csrf(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", { credentials: "include" });
  if (!response.ok) throw new Error("无法获取 CSRF Token");
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

async function problem(response: Response): Promise<never> {
  const details = (await response
    .json()
    .catch(() => null)) as ProblemDetails | null;
  throw new Error(details?.detail ?? `请求失败（${response.status}）`);
}

export function GenerationForm({
  workspaceId,
  workflows,
  providers,
  prompts,
  ruleSets,
}: {
  workspaceId: string;
  workflows: GenerationWorkflow[];
  providers: LLMProviderDescriptor[];
  prompts: PromptCollectionSummary[];
  ruleSets: EditorialRuleSetSummary[];
}) {
  const router = useRouter();
  const search = useSearchParams();
  const [workflowId, setWorkflowId] = useState(workflows[0]?.id ?? "");
  const [inputType, setInputType] = useState(
    search.get("input_type") ?? "user_text",
  );
  const [inputId, setInputId] = useState(search.get("input_id") ?? "");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [answerWord, setAnswerWord] = useState("");
  const [ruleVersionId, setRuleVersionId] = useState("");
  const [promptVersionId, setPromptVersionId] = useState("");
  const [provider, setProvider] = useState("mock_llm");
  const [model, setModel] = useState("mock-sports-writer-v1");
  const [temperature, setTemperature] = useState(0.4);
  const [topP, setTopP] = useState(1);
  const [maxTokens, setMaxTokens] = useState(4096);
  const [targetMin, setTargetMin] = useState(1200);
  const [targetMax, setTargetMax] = useState(1250);
  const [preview, setPreview] = useState<{
    system_prompt: string;
    user_prompt: string;
    warnings: string[];
  } | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const selectedWorkflow = workflows.find((item) => item.id === workflowId);
  const payload = useMemo(
    () => ({
      workflow_id: workflowId,
      input_type: inputType,
      input_id: inputType === "user_text" ? null : inputId || null,
      input_payload:
        inputType === "user_text"
          ? {
              title,
              text,
              language: "zh-CN",
              ...(answerWord.trim()
                ? {
                    answer_word: answerWord.trim(),
                    answer_reveal_min_ratio: 0.55,
                  }
                : {}),
            }
          : {},
      rule_set_version_id: ruleVersionId || null,
      prompt_version_id: promptVersionId || null,
      provider,
      model,
      model_config: {
        temperature,
        top_p: topP,
        max_tokens: maxTokens,
        target_min_chars: targetMin,
        target_max_chars: targetMax,
        max_rewrites: 2,
      },
    }),
    [
      workflowId,
      inputType,
      inputId,
      title,
      text,
      answerWord,
      ruleVersionId,
      promptVersionId,
      provider,
      model,
      temperature,
      topP,
      maxTokens,
      targetMin,
      targetMax,
    ],
  );

  async function submit(mode: "preview" | "execute") {
    setBusy(true);
    setStatus(mode === "preview" ? "正在渲染安全预览…" : "正在创建生成任务…");
    try {
      const token = await csrf();
      const response = await fetch(
        mode === "preview"
          ? "/api/v1/generations/preview"
          : "/api/v1/generations",
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": token,
            "X-Workspace-Id": workspaceId,
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) await problem(response);
      if (mode === "preview") {
        const result = (await response.json()) as {
          system_prompt: string;
          user_prompt: string;
          warnings: string[];
        };
        setPreview(result);
        setStatus("Prompt 预览已生成；密钥不会出现在预览中。 ");
      } else {
        const result = (await response.json()) as { id: string };
        router.push(`/generations/${result.id}`);
      }
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.8fr)]">
      <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6">
        <div className="grid gap-5 md:grid-cols-2">
          <label className="text-xs text-slate-400">
            工作流
            <select
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              onChange={(event) => setWorkflowId(event.target.value)}
              value={workflowId}
            >
              {workflows.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            输入类型
            <select
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              onChange={(event) => setInputType(event.target.value)}
              value={inputType}
            >
              {(selectedWorkflow?.input_types ?? ["user_text"]).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>
        {inputType === "user_text" ? (
          <div className="mt-5 space-y-4">
            <input
              className="w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              onChange={(event) => setTitle(event.target.value)}
              placeholder="事件标题"
              value={title}
            />
            <textarea
              className="min-h-52 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm leading-6"
              onChange={(event) => setText(event.target.value)}
              placeholder="输入事件事实。系统会标记为 imported；没有可追溯来源时不会声称已联网核实。"
              value={text}
            />
            <input
              className="w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              onChange={(event) => setAnswerWord(event.target.value)}
              placeholder="受保护答案词（可选；默认不得在文案前 55% 出现）"
              value={answerWord}
            />
          </div>
        ) : (
          <label className="mt-5 block text-xs text-slate-400">
            资源 ID
            <input
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 font-mono text-sm"
              onChange={(event) => setInputId(event.target.value)}
              placeholder="新闻、事件或作品 UUID"
              value={inputId}
            />
          </label>
        )}

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <label className="text-xs text-slate-400">
            规则版本
            <select
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              onChange={(event) => setRuleVersionId(event.target.value)}
              value={ruleVersionId}
            >
              <option value="">工作流默认 7.9 规则</option>
              {ruleSets
                .filter((item) => item.current_version_id)
                .map((item) => (
                  <option key={item.id} value={item.current_version_id ?? ""}>
                    {item.name}
                  </option>
                ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            Prompt 版本
            <select
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              onChange={(event) => setPromptVersionId(event.target.value)}
              value={promptVersionId}
            >
              <option value="">工作流默认 Prompt</option>
              {prompts
                .filter((item) => item.current_version_id)
                .map((item) => (
                  <option key={item.id} value={item.current_version_id ?? ""}>
                    {item.name}
                  </option>
                ))}
            </select>
          </label>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <label className="text-xs text-slate-400">
            LLM Provider
            <select
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              onChange={(event) => {
                const key = event.target.value;
                const descriptor = providers.find((item) => item.key === key);
                setProvider(key);
                setModel(descriptor?.default_model ?? "");
                setTemperature(
                  numericDefault(
                    descriptor?.default_parameters.temperature,
                    0.4,
                  ),
                );
                setTopP(
                  numericDefault(descriptor?.default_parameters.top_p, 1),
                );
                setMaxTokens(
                  numericDefault(
                    descriptor?.default_parameters.max_tokens,
                    4096,
                  ),
                );
              }}
              value={provider}
            >
              {providers.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.name} {item.configured ? "" : "（未配置）"}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            模型
            <input
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              onChange={(event) => setModel(event.target.value)}
              value={model}
            />
          </label>
        </div>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <label className="text-xs text-slate-400">
            Temperature
            <input
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              max={2}
              min={0}
              onChange={(event) => setTemperature(Number(event.target.value))}
              step={0.1}
              type="number"
              value={temperature}
            />
          </label>
          <label className="text-xs text-slate-400">
            Top P
            <input
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              max={1}
              min={0}
              onChange={(event) => setTopP(Number(event.target.value))}
              step={0.05}
              type="number"
              value={topP}
            />
          </label>
          <label className="text-xs text-slate-400">
            最大 Token
            <input
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              max={131072}
              min={1}
              onChange={(event) => setMaxTokens(Number(event.target.value))}
              type="number"
              value={maxTokens}
            />
          </label>
          <label className="text-xs text-slate-400">
            最少字符
            <input
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              min={200}
              onChange={(event) => setTargetMin(Number(event.target.value))}
              type="number"
              value={targetMin}
            />
          </label>
          <label className="text-xs text-slate-400">
            最多字符
            <input
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              max={5000}
              onChange={(event) => setTargetMax(Number(event.target.value))}
              type="number"
              value={targetMax}
            />
          </label>
        </div>
        {provider === "mock_llm" ? (
          <p className="mt-5 rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-xs text-amber-200">
            Mock LLM 只产生明确标记的测试输出，不代表真实 AI 或联网核实结果。
          </p>
        ) : null}
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            className="rounded-lg border border-slate-700 px-4 py-2.5 text-sm text-slate-200 disabled:opacity-50"
            disabled={busy || !workflowId}
            onClick={() => submit("preview")}
            type="button"
          >
            预览最终 Prompt
          </button>
          <button
            className="rounded-lg bg-cyan-300 px-4 py-2.5 text-sm font-semibold text-slate-950 disabled:opacity-50"
            disabled={
              busy ||
              !workflowId ||
              (inputType === "user_text" ? !text.trim() : !inputId)
            }
            onClick={() => submit("execute")}
            type="button"
          >
            {busy ? "处理中…" : "执行工作流"}
          </button>
        </div>
        {status ? (
          <p className="mt-4 text-sm text-slate-300" role="status">
            {status}
          </p>
        ) : null}
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6">
        <h2 className="text-lg font-semibold text-white">安全 Prompt 预览</h2>
        {!preview ? (
          <p className="mt-4 text-sm text-slate-500">
            预览会显示固定 Prompt 版本、变量和规则编译结果；API Key
            始终只在后端使用。
          </p>
        ) : (
          <div className="mt-5 space-y-5">
            <div>
              <h3 className="text-xs font-semibold text-cyan-300 uppercase">
                System
              </h3>
              <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 text-xs leading-5 text-slate-300">
                {preview.system_prompt}
              </pre>
            </div>
            <div>
              <h3 className="text-xs font-semibold text-cyan-300 uppercase">
                User
              </h3>
              <pre className="mt-2 max-h-[30rem] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 text-xs leading-5 text-slate-300">
                {preview.user_prompt}
              </pre>
            </div>
            <ul className="space-y-2 text-xs text-amber-200">
              {preview.warnings.map((item) => (
                <li key={item}>• {item}</li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}

function numericDefault(value: unknown, fallback: number): number {
  if (typeof value !== "number" && typeof value !== "string") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}
