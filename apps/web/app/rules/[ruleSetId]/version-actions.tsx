"use client";

import type { ProblemDetails } from "@sio/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function VersionActions({
  workspaceId,
  ruleSetId,
  currentVersionId,
}: {
  workspaceId: string;
  ruleSetId: string;
  currentVersionId: string | null;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function createDraft() {
    if (!currentVersionId) return;
    setBusy(true);
    setError(null);
    try {
      const csrf = await fetch("/api/v1/auth/csrf", { credentials: "include" });
      const token = ((await csrf.json()) as { csrf_token: string }).csrf_token;
      const response = await fetch(`/api/v1/rules/${ruleSetId}/versions`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": token,
          "X-Workspace-Id": workspaceId,
        },
        body: JSON.stringify({
          from_version_id: currentVersionId,
          changelog: "从当前发布版本创建编辑草稿",
        }),
      });
      if (!response.ok) {
        const problem = (await response
          .json()
          .catch(() => null)) as ProblemDetails | null;
        throw new Error(problem?.detail ?? "创建草稿失败");
      }
      const version = (await response.json()) as { id: string };
      router.push(`/rules/${ruleSetId}/edit?version=${version.id}`);
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建草稿失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="text-right">
      <button
        className="rounded-lg border border-cyan-800 px-3 py-2 text-sm text-cyan-200 disabled:opacity-50"
        disabled={busy || !currentVersionId}
        onClick={createDraft}
        type="button"
      >
        {busy ? "创建中…" : "创建新草稿"}
      </button>
      {error ? <p className="mt-2 text-xs text-rose-300">{error}</p> : null}
    </div>
  );
}
