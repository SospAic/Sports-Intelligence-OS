"use client";

import type { ProblemDetails } from "@sio/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function VersionLifecycle({
  workspaceId,
  ruleSetId,
  versionId,
  status,
}: {
  workspaceId: string;
  ruleSetId: string;
  versionId: string;
  status: "draft" | "published" | "archived";
}) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function action(kind: "publish" | "rollback") {
    setBusy(true);
    try {
      const csrfResponse = await fetch("/api/v1/auth/csrf", {
        credentials: "include",
      });
      const token = ((await csrfResponse.json()) as { csrf_token: string })
        .csrf_token;
      const response = await fetch(
        `/api/v1/rules/${ruleSetId}/versions/${versionId}/${kind}`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": token,
            "X-Workspace-Id": workspaceId,
          },
          body: JSON.stringify({
            reason: kind === "publish" ? "版本页面发布" : "版本页面回滚",
          }),
        },
      );
      if (!response.ok) {
        const detail = (await response
          .json()
          .catch(() => null)) as ProblemDetails | null;
        throw new Error(detail?.detail ?? "版本操作失败");
      }
      setMessage(kind === "publish" ? "版本已发布" : "当前版本已回滚到此版本");
      router.refresh();
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "版本操作失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {status === "draft" ? (
        <button
          className="rounded-lg border border-emerald-800 px-3 py-2 text-sm text-emerald-200"
          disabled={busy}
          onClick={() => action("publish")}
          type="button"
        >
          发布
        </button>
      ) : status === "published" ? (
        <button
          className="rounded-lg border border-amber-800 px-3 py-2 text-sm text-amber-200"
          disabled={busy}
          onClick={() => action("rollback")}
          type="button"
        >
          回滚到此版本
        </button>
      ) : null}
      {message ? (
        <span className="text-xs text-slate-400">{message}</span>
      ) : null}
    </div>
  );
}
