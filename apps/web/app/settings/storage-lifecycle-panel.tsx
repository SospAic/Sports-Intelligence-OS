"use client";

import { useQuery } from "@tanstack/react-query";
import { HardDrive, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Badge, Panel, StatePanel, secondaryButtonClass } from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";

type StorageHealth = {
  media_bytes: number;
  media_file_count: number;
  tracked_artifact_count: number;
  tracked_ready_count: number;
  orphan_file_count: number | null;
  orphan_bytes: number | null;
  quota_bytes: number | null;
  quota_percent: number | null;
  warnings: string[];
  policy: Record<string, unknown>;
};

type StorageLifecycle = {
  dry_run: boolean;
  automatic_cleanup_enabled: boolean;
  scanned_file_count: number;
  candidates: Array<{
    relative_path: string;
    kind: string;
    size_bytes: number | null;
    reason: string;
  }>;
  deleted_file_count: number;
  deleted_bytes: number;
  marked_stale_count: number;
  failed: Array<{ path: string; error: string }>;
  skipped: Record<string, number>;
};

function formatBytes(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value;
  let index = -1;
  do {
    amount /= 1024;
    index += 1;
  } while (amount >= 1024 && index < units.length - 1);
  return `${amount.toFixed(amount >= 10 ? 0 : 1)} ${units[index]}`;
}

export function StorageLifecyclePanel({
  workspaceId,
  role,
}: {
  workspaceId: string;
  role: string | null;
}) {
  const { notify } = useToast();
  const [running, setRunning] = useState(false);
  const canManage = role === "owner" || role === "admin";
  const health = useQuery({
    queryKey: ["storage-health", workspaceId],
    queryFn: () => apiRequest<StorageHealth>("/storage/health", { workspaceId }),
    enabled: Boolean(workspaceId),
  });
  const lifecycle = useQuery({
    queryKey: ["storage-lifecycle", workspaceId],
    queryFn: () => apiRequest<StorageLifecycle>("/storage/lifecycle", { workspaceId }),
    enabled: Boolean(workspaceId),
  });

  async function preview() {
    await lifecycle.refetch();
    await health.refetch();
    notify("存储生命周期预览已刷新");
  }

  async function execute() {
    if (!canManage || !window.confirm("确认按当前预览策略执行物理文件清理吗？")) return;
    setRunning(true);
    try {
      const result = await apiRequest<StorageLifecycle>("/storage/lifecycle", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ confirm: true, dry_run: false }),
      });
      notify(
        result.dry_run
          ? "策略仍处于 dry-run 或未启用，未删除文件"
          : `已清理 ${result.deleted_file_count} 个文件`,
        result.failed.length ? "error" : "success",
      );
      await preview();
    } catch (error) {
      notify(error instanceof Error ? error.message : "存储清理失败", "error");
    } finally {
      setRunning(false);
    }
  }

  if (health.isError || lifecycle.isError) {
    return (
      <StatePanel
        type="error"
        title="存储治理状态加载失败"
        detail={(health.error ?? lifecycle.error)?.message}
        onRetry={preview}
      />
    );
  }

  const healthData = health.data;
  const lifecycleData = lifecycle.data;
  return (
    <div className="space-y-5">
      <Panel className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <HardDrive size={17} className="text-cyan-300" />
              <h2 className="font-medium text-white">媒体存储生命周期</h2>
              <Badge tone={lifecycleData?.dry_run ? "warning" : "success"}>
                {lifecycleData?.dry_run ? "只读 / dry-run" : "已执行"}
              </Badge>
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              只清理已明确标记为 temporary 的过期制品和工作区孤儿文件；managed / protected 永不自动删除。
            </p>
          </div>
          <div className="flex gap-2">
            <button type="button" className={secondaryButtonClass} onClick={preview} disabled={running}>
              <RefreshCw size={14} /> 预览
            </button>
            <button
              type="button"
              className={`${secondaryButtonClass} text-rose-300`}
              onClick={execute}
              disabled={running || !canManage || !lifecycleData?.candidates.length}
              title={canManage ? "执行前必须确认" : "需要 Owner/Admin"}
            >
              <Trash2 size={14} /> {running ? "处理中…" : "执行清理"}
            </button>
          </div>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="媒体体积" value={formatBytes(healthData?.media_bytes)} />
          <Stat label="已登记 / 已就绪" value={`${healthData?.tracked_artifact_count ?? 0} / ${healthData?.tracked_ready_count ?? 0}`} />
          <Stat label="孤儿文件" value={healthData?.orphan_file_count == null ? "扫描不完整" : String(healthData.orphan_file_count)} />
          <Stat label="本次候选" value={String(lifecycleData?.candidates.length ?? 0)} />
        </div>
      </Panel>
      {healthData?.warnings.map((warning) => (
        <Panel key={warning} className="border-amber-900/60 bg-amber-950/20 p-4 text-xs text-amber-200">
          {warning}
        </Panel>
      ))}
      <Panel className="p-5">
        <div className="flex items-center gap-2 text-sm text-slate-200">
          <ShieldCheck size={15} className="text-emerald-300" />
          <span>生命周期候选</span>
        </div>
        {!lifecycleData?.candidates.length ? (
          <p className="mt-4 text-sm text-slate-500">当前没有满足保留期的清理候选。</p>
        ) : (
          <div className="mt-3 divide-y divide-slate-800 rounded-xl border border-slate-800">
            {lifecycleData.candidates.slice(0, 50).map((candidate) => (
              <div key={candidate.relative_path} className="flex flex-wrap justify-between gap-2 px-3 py-2 text-xs">
                <span className="break-all text-slate-300">{candidate.relative_path}</span>
                <span className="text-slate-500">{candidate.kind} · {formatBytes(candidate.size_bytes)}</span>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className="mt-1 text-lg text-slate-200">{value}</p>
    </div>
  );
}
