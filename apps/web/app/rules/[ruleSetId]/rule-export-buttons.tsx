"use client";

import { useState } from "react";

export function RuleExportButtons({
  workspaceId,
  ruleSetId,
  versionId,
}: {
  workspaceId: string;
  ruleSetId: string;
  versionId: string;
}) {
  const [error, setError] = useState<string | null>(null);

  async function download(format: "txt" | "json") {
    setError(null);
    const response = await fetch(
      `/api/v1/rules/${ruleSetId}/versions/${versionId}/export?format=${format}`,
      {
        credentials: "include",
        headers: { "X-Workspace-Id": workspaceId },
      },
    );
    if (!response.ok) {
      setError("导出失败");
      return;
    }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `rules-${versionId}.${format}`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex items-center gap-2">
      {(["txt", "json"] as const).map((format) => (
        <button
          className="rounded border border-slate-700 px-2.5 py-1.5 text-xs text-slate-300"
          key={format}
          onClick={() => download(format)}
          type="button"
        >
          {format.toUpperCase()}
        </button>
      ))}
      {error ? <span className="text-xs text-rose-300">{error}</span> : null}
    </div>
  );
}
