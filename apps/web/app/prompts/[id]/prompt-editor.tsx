"use client";

import type { ProblemDetails, PromptVersion } from "@sio/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

async function csrf(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", { credentials: "include" });
  if (!response.ok) throw new Error("无法获取 CSRF Token");
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

export function PromptEditor({
  workspaceId,
  collectionId,
  version,
}: {
  workspaceId: string;
  collectionId: string;
  version: PromptVersion;
}) {
  const router = useRouter();
  const [systemPrompt, setSystemPrompt] = useState(version.system_prompt);
  const [userPrompt, setUserPrompt] = useState(version.user_prompt_template);
  const [schema, setSchema] = useState(
    JSON.stringify(version.variables_schema, null, 2),
  );
  const [config, setConfig] = useState(
    JSON.stringify(version.model_config, null, 2),
  );
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function request(action: "save" | "publish" | "rollback") {
    setBusy(true);
    try {
      const response = await fetch(
        `/api/v1/prompts/${collectionId}/versions/${version.id}${action === "save" ? "" : `/${action}`}`,
        {
          method: action === "save" ? "PATCH" : "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": await csrf(),
            "X-Workspace-Id": workspaceId,
          },
          body:
            action === "save"
              ? JSON.stringify({
                  system_prompt: systemPrompt,
                  user_prompt_template: userPrompt,
                  variables_schema: JSON.parse(schema),
                  model_config: JSON.parse(config),
                })
              : "{}",
        },
      );
      if (!response.ok) {
        const problem = (await response
          .json()
          .catch(() => null)) as ProblemDetails | null;
        throw new Error(problem?.detail ?? "操作失败");
      }
      const result = (await response.json()) as PromptVersion;
      setStatus(
        action === "save"
          ? "草稿已保存"
          : `版本已${action === "publish" ? "发布" : "回滚"}`,
      );
      router.replace(`/prompts/${collectionId}?version=${result.id}`);
      router.refresh();
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="space-y-5 rounded-2xl border border-slate-800 bg-slate-950/70 p-6">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold text-white">Prompt 正文</h2>
          <span className="rounded-full border border-slate-700 px-2.5 py-1 text-xs text-slate-400">
            {version.version} · {version.status}
          </span>
        </div>
        <label className="block text-xs text-slate-400">
          System Prompt
          <textarea
            className="mt-2 min-h-48 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm leading-6"
            onChange={(event) => setSystemPrompt(event.target.value)}
            value={systemPrompt}
          />
        </label>
        <label className="block text-xs text-slate-400">
          User Prompt Template
          <textarea
            className="mt-2 min-h-96 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 font-mono text-xs leading-5"
            onChange={(event) => setUserPrompt(event.target.value)}
            value={userPrompt}
          />
        </label>
      </div>
      <aside className="space-y-5 rounded-2xl border border-slate-800 bg-slate-950/70 p-6">
        <label className="block text-xs text-slate-400">
          Variables JSON Schema
          <textarea
            className="mt-2 min-h-72 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 font-mono text-xs leading-5"
            onChange={(event) => setSchema(event.target.value)}
            value={schema}
          />
        </label>
        <label className="block text-xs text-slate-400">
          Model Config
          <textarea
            className="mt-2 min-h-48 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 font-mono text-xs leading-5"
            onChange={(event) => setConfig(event.target.value)}
            value={config}
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            className="rounded bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50"
            disabled={busy}
            onClick={() => request("save")}
            type="button"
          >
            保存草稿
          </button>
          <button
            className="rounded border border-emerald-800 px-3 py-2 text-xs text-emerald-200 disabled:opacity-50"
            disabled={busy || version.status !== "draft"}
            onClick={() => request("publish")}
            type="button"
          >
            发布
          </button>
          <button
            className="rounded border border-slate-700 px-3 py-2 text-xs disabled:opacity-50"
            disabled={busy || version.status !== "published"}
            onClick={() => request("rollback")}
            type="button"
          >
            回滚到此版本
          </button>
        </div>
        {status ? <p className="text-xs text-slate-300">{status}</p> : null}
      </aside>
    </section>
  );
}
