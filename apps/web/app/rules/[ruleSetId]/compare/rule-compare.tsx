"use client";

import type {
  EditorialRuleVersionSummary,
  ProblemDetails,
} from "@sio/shared-types";
import { useState } from "react";

interface Diff {
  added: number;
  removed: number;
  modified: number;
  unchanged: number;
  items: Array<{
    key: string;
    change: "added" | "removed" | "modified";
    fields: string[];
  }>;
}

export function RuleCompare({
  workspaceId,
  ruleSetId,
  versions,
}: {
  workspaceId: string;
  ruleSetId: string;
  versions: EditorialRuleVersionSummary[];
}) {
  const [left, setLeft] = useState(versions[1]?.id ?? versions[0]?.id ?? "");
  const [right, setRight] = useState(versions[0]?.id ?? "");
  const [diff, setDiff] = useState<Diff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function compare() {
    if (!left || !right) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/rules/${ruleSetId}/compare?left=${left}&right=${right}`,
        { credentials: "include", headers: { "X-Workspace-Id": workspaceId } },
      );
      if (!response.ok) {
        const detail = (await response
          .json()
          .catch(() => null)) as ProblemDetails | null;
        throw new Error(detail?.detail ?? "版本对比失败");
      }
      setDiff((await response.json()) as Diff);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "版本对比失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-8 rounded-2xl border border-slate-800 bg-slate-950/70 p-6">
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
        <select
          className="rounded-lg border border-slate-700 bg-slate-900 p-2 text-sm"
          onChange={(event) => setLeft(event.target.value)}
          value={left}
        >
          {versions.map((version) => (
            <option key={version.id} value={version.id}>
              {version.version} · {version.status}
            </option>
          ))}
        </select>
        <select
          className="rounded-lg border border-slate-700 bg-slate-900 p-2 text-sm"
          onChange={(event) => setRight(event.target.value)}
          value={right}
        >
          {versions.map((version) => (
            <option key={version.id} value={version.id}>
              {version.version} · {version.status}
            </option>
          ))}
        </select>
        <button
          className="rounded-lg bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950"
          disabled={busy || left === right}
          onClick={compare}
          type="button"
        >
          {busy ? "对比中…" : "开始对比"}
        </button>
      </div>
      {error ? <p className="mt-5 text-sm text-rose-300">{error}</p> : null}
      {diff ? (
        <div className="mt-6">
          <div className="grid gap-3 text-sm sm:grid-cols-4">
            <span className="rounded-lg border border-emerald-900 p-3 text-emerald-200">
              新增 {diff.added}
            </span>
            <span className="rounded-lg border border-rose-900 p-3 text-rose-200">
              删除 {diff.removed}
            </span>
            <span className="rounded-lg border border-amber-900 p-3 text-amber-200">
              修改 {diff.modified}
            </span>
            <span className="rounded-lg border border-slate-700 p-3 text-slate-300">
              未变 {diff.unchanged}
            </span>
          </div>
          <ul className="mt-5 max-h-[55vh] divide-y divide-slate-800 overflow-auto">
            {diff.items.map((item) => (
              <li
                className="grid gap-2 py-3 text-sm sm:grid-cols-[240px_100px_1fr]"
                key={`${item.change}-${item.key}`}
              >
                <span className="font-mono text-xs text-cyan-300">
                  {item.key}
                </span>
                <span className="text-slate-300">{item.change}</span>
                <span className="text-xs text-slate-500">
                  {item.fields.join(", ") || "整条规则"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
