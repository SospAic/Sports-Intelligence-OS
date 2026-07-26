"use client";

import type { GenerationRun, ProblemDetails } from "@sio/shared-types";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

async function csrf(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", { credentials: "include" });
  if (!response.ok) throw new Error("无法获取 CSRF Token");
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

async function fail(response: Response): Promise<never> {
  const problem = (await response
    .json()
    .catch(() => null)) as ProblemDetails | null;
  throw new Error(problem?.detail ?? `请求失败（${response.status}）`);
}

export function GenerationDetail({
  workspaceId,
  run,
}: {
  workspaceId: string;
  run: GenerationRun;
}) {
  const router = useRouter();
  const [status, setStatus] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const output = useMemo(() => run.final_output ?? {}, [run.final_output]);
  const tts = typeof output.tts_en === "string" ? output.tts_en : "";
  const isActive = run.status === "queued" || run.status === "running";
  const outputEntries = useMemo(
    () =>
      Object.entries(output).filter(
        ([key]) => !["qa_report", "used_rules", "fact_sources"].includes(key),
      ),
    [output],
  );

  useEffect(() => {
    if (!isActive) return;
    const timer = window.setInterval(() => router.refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [isActive, router]);

  async function action(kind: "retry" | "rewrite" | "save") {
    setBusy(true);
    try {
      const endpoint =
        kind === "save"
          ? `/api/v1/generations/${run.id}/decision`
          : `/api/v1/generations/${run.id}/${kind}`;
      const response = await fetch(endpoint, {
        method: kind === "save" ? "PATCH" : "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": await csrf(),
          "X-Workspace-Id": workspaceId,
        },
        body: JSON.stringify(
          kind === "rewrite"
            ? { instruction }
            : kind === "save"
              ? { is_saved: !run.is_saved }
              : {},
        ),
      });
      if (!response.ok) await fail(response);
      const result = (await response.json()) as GenerationRun;
      if (kind === "rewrite") router.push(`/generations/${result.id}`);
      else {
        setStatus(kind === "save" ? "采用状态已保存" : "已重新加入队列");
        router.refresh();
      }
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function download(format: "json" | "txt") {
    const response = await fetch(
      `/api/v1/generations/${run.id}/export?format=${format}`,
      { headers: { "X-Workspace-Id": workspaceId }, credentials: "include" },
    );
    if (!response.ok) return setStatus("导出失败");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `generation-${run.id}.${format}`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-7xl">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs text-cyan-300">{run.id}</p>
          <h1 className="mt-3 text-3xl font-semibold text-white">
            生成运行详情
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            {run.provider} · {run.model} · {run.verification_status}
          </p>
        </div>
        <span className="rounded-full border border-slate-700 px-3 py-1.5 text-sm text-slate-200">
          {run.status}
        </span>
      </div>

      {run.metadata.provider_is_mock ? (
        <p className="mt-6 rounded-xl border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-200">
          这是 Mock LLM 测试运行。输出不得作为真实 AI 生成或已核实平台内容使用。
        </p>
      ) : null}
      {run.error ? (
        <div className="mt-6 rounded-xl border border-rose-900/60 bg-rose-950/20 p-4 text-sm text-rose-200">
          {run.error.code}: {run.error.message}
          <button
            className="ml-4 rounded border border-rose-800 px-3 py-1 text-xs"
            disabled={busy}
            onClick={() => action("retry")}
            type="button"
          >
            重试
          </button>
        </div>
      ) : null}

      <section className="mt-8 rounded-2xl border border-slate-800 bg-slate-950/70 p-6">
        <h2 className="text-lg font-semibold text-white">工作流步骤</h2>
        <ol className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {run.steps.map((step) => (
            <li
              className="rounded-xl border border-slate-800 p-4"
              key={step.id}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-slate-500">
                  {step.sort_order}/10
                </span>
                <span className="text-[11px] text-cyan-300">{step.status}</span>
              </div>
              <p className="mt-2 text-sm font-medium text-slate-200">
                {step.name}
              </p>
              {step.error ? (
                <p className="mt-2 text-xs text-rose-300">
                  {String(step.error.message ?? "步骤失败")}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
        <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-white">最终内容包</h2>
            <div className="flex gap-2">
              <button
                className="rounded border border-slate-700 px-3 py-1.5 text-xs"
                disabled={!tts}
                onClick={() => navigator.clipboard.writeText(tts)}
                type="button"
              >
                复制 TTS
              </button>
              <button
                className="rounded border border-slate-700 px-3 py-1.5 text-xs"
                onClick={() => download("json")}
                type="button"
              >
                导出 JSON
              </button>
              <button
                className="rounded border border-slate-700 px-3 py-1.5 text-xs"
                onClick={() => download("txt")}
                type="button"
              >
                导出 TXT
              </button>
            </div>
          </div>
          {outputEntries.length === 0 ? (
            <p className="mt-5 text-sm text-slate-500">
              {isActive ? "任务执行中，页面会自动刷新。" : "尚无最终输出。"}
            </p>
          ) : (
            <dl className="mt-5 space-y-5">
              {outputEntries.map(([key, value]) => (
                <div key={key}>
                  <dt className="text-xs font-semibold text-cyan-300 uppercase">
                    {key}
                  </dt>
                  <dd className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-300">
                    {typeof value === "string"
                      ? value
                      : JSON.stringify(value, null, 2)}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </section>
        <aside className="space-y-6">
          <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6">
            <h2 className="text-lg font-semibold text-white">QA 与成本</h2>
            <pre className="mt-4 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 text-xs text-slate-300">
              {JSON.stringify(run.validation_result, null, 2)}
            </pre>
            <div className="mt-4 grid grid-cols-2 gap-3 text-xs text-slate-400">
              <span>重写 {run.rewrite_count} 次</span>
              <span>成本 {run.estimated_cost ?? "unavailable"}</span>
              <span>Token {String(run.token_usage.total_tokens ?? 0)}</span>
              <span>{run.is_saved ? "已采用" : "未采用"}</span>
            </div>
            <button
              className="mt-4 rounded border border-emerald-800 px-3 py-2 text-xs text-emerald-200"
              disabled={busy || run.status !== "completed"}
              onClick={() => action("save")}
              type="button"
            >
              {run.is_saved ? "取消采用" : "保存并采用"}
            </button>
          </section>
          <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6">
            <h2 className="text-lg font-semibold text-white">手动重写</h2>
            <textarea
              className="mt-4 min-h-28 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
              onChange={(event) => setInstruction(event.target.value)}
              placeholder="说明需要修改的内容；系统会创建新运行，不覆盖历史结果。"
              value={instruction}
            />
            <button
              className="mt-3 rounded bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50"
              disabled={
                busy || run.status !== "completed" || !instruction.trim()
              }
              onClick={() => action("rewrite")}
              type="button"
            >
              创建重写运行
            </button>
            {status ? (
              <p className="mt-3 text-xs text-slate-300">{status}</p>
            ) : null}
          </section>
        </aside>
      </div>
    </div>
  );
}
