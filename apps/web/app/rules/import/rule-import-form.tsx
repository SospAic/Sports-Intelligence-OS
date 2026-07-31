"use client";

import type { ProblemDetails } from "@sio/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

async function csrfToken(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", { credentials: "include" });
  if (!response.ok) throw new Error("无法获取 CSRF Token");
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

export function RuleImportForm({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [publishing, setPublishing] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    if (!file) return setStatus("请选择 TXT 或 JSON 文件");
    setSubmitting(true);
    setStatus("正在读取并校验文件…");
    try {
      const token = await csrfToken();
      const format = file.name.toLowerCase().endsWith(".json") ? "json" : "txt";
      const response = await fetch("/api/v1/rules/import", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": token,
          "X-Workspace-Id": workspaceId,
        },
        body: JSON.stringify({
          format,
          filename: file.name,
          content: await file.text(),
          publish: publishing,
        }),
      });
      if (!response.ok) {
        const problem = (await response
          .json()
          .catch(() => null)) as ProblemDetails | null;
        throw new Error(problem?.detail ?? "导入失败");
      }
      const result = (await response.json()) as {
        rule_set: { id: string };
        version: { rule_count: number; section_count: number };
        created: boolean;
      };
      setStatus(
        `${result.created ? "导入完成" : "相同原文已存在"}：${result.version.section_count} 个章节，${result.version.rule_count} 条规则。`,
      );
      router.push(`/rules/${result.rule_set.id}`);
      router.refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "导入失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="mt-8 rounded-2xl border border-slate-800 bg-slate-950/70 p-6">
      <label className="block text-sm text-slate-300">
        规则文件
        <input
          accept=".txt,.json,text/plain,application/json"
          className="mt-2 block w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          type="file"
        />
      </label>
      <label className="mt-5 flex items-center gap-3 text-sm text-slate-300">
        <input
          checked={publishing}
          onChange={(event) => setPublishing(event.target.checked)}
          type="checkbox"
        />
        校验通过后立即发布；关闭时保存为草稿
      </label>
      {status ? (
        <p className="mt-5 rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm text-slate-200">
          {status}
        </p>
      ) : null}
      <button
        className="mt-6 rounded-lg bg-cyan-300 px-4 py-2.5 text-sm font-semibold text-slate-950 disabled:opacity-50"
        disabled={submitting || !file}
        onClick={submit}
        type="button"
      >
        {submitting ? "正在导入…" : "导入并解析"}
      </button>
    </section>
  );
}
