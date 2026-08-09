"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clock3,
  Database,
  Layers,
  Network,
  RefreshCw,
} from "lucide-react";
import { useState } from "react";

import { useWorkspace } from "@/components/app-shell";
import { Badge, Panel, StatePanel, buttonClass } from "@/components/ui";
import { useToast } from "@/components/toast";
import { apiRequest } from "@/lib/browser-api";

/* ========================================================================== */
/*  Types                                                                      */
/* ========================================================================== */

type ChunkKind = "meta" | "subtitle" | "transcript";
type StatusResponse = {
  enabled: boolean;
  backend: string;
  model: string | null;
  dimension: number;
  embedded_chunks: number;
  embedded_items: number;
  pending_items: number;
  chunk_kinds: Record<string, number>;
};

const CHUNK_KIND_LABELS: Record<ChunkKind, string> = {
  meta: "元数据",
  subtitle: "字幕",
  transcript: "转写",
};

function formatNumber(value: number): string {
  return value.toLocaleString("en-US");
}

/* ========================================================================== */
/*  Component                                                                  */
/* ========================================================================== */

export function SemanticSearchSettingsPanel() {
  const { workspaceId } = useWorkspace();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [reindexFull, setReindexFull] = useState(false);
  const [reindexing, setReindexing] = useState(false);

  const status = useQuery<StatusResponse>({
    queryKey: ["semantic-search-status", workspaceId],
    queryFn: () =>
      apiRequest<StatusResponse>("/semantic-search/status", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
    refetchInterval: 15_000,
  });

  const disabled = !status.data?.enabled;

  const pendingKindTotal = Object.values(status.data?.chunk_kinds ?? {}).reduce(
    (sum, count) => sum + count,
    0,
  );

  async function triggerReindex() {
    if (!workspaceId) return;
    setReindexing(true);
    try {
      await apiRequest("/semantic-search/reindex", {
        method: "POST",
        csrf: true,
        workspaceId,
        body: JSON.stringify({ limit: 500, reindex: reindexFull }),
      });
      notify(reindexFull ? "已提交全量重建任务" : "已提交增量索引任务", "success");
      void queryClient.invalidateQueries({ queryKey: ["semantic-search-status"] });
    } catch (error) {
      const message = (error as Error).message;
      if (message.includes("embedding_backend_disabled")) {
        notify("未配置 embedding 后端，无法索引", "error");
      } else if (message.includes("403")) {
        notify("需要 owner / admin / editor 权限才能重建索引", "error");
      } else {
        notify(`索引任务提交失败：${message}`, "error");
      }
    } finally {
      setReindexing(false);
    }
  }

  return (
    <div className="space-y-6">
      <Panel className="p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-white">本地语义检索 · 索引管理</h2>
            <p className="mt-1 text-xs text-slate-500">
              向量索引健康度与重建管理。完全本地、不调用 LLM 的混合向量 + 关键词召回。
            </p>
          </div>
          <Database size={19} className="text-cyan-400" />
        </div>

        {status.isLoading ? (
          <div className="p-6 text-sm text-slate-500">加载索引状态…</div>
        ) : status.isError ? (
          <StatePanel type="error" title="状态加载失败" detail="请检查 API 与工作区状态。" />
        ) : disabled ? (
          <StatePanel
            type="empty"
            title="本地检索未启用"
            detail="服务端未配置 embedding 后端（SIO_EMBEDDING_BACKEND）。设置 BGE-M3 / TEI 等后端并开启 SIO_SEMANTIC_SEARCH_ENABLED 后，此处会显示索引状态。"
          />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <Stat label="已索引内容" value={formatNumber(status.data?.embedded_items ?? 0)} />
              <Stat label="已索引块" value={formatNumber(status.data?.embedded_chunks ?? 0)} />
              <Stat
                label="待索引"
                value={formatNumber(status.data?.pending_items ?? 0)}
                tone={(status.data?.pending_items ?? 0) > 0 ? "warning" : "default"}
              />
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-xs leading-5 text-slate-400">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Network size={13} className="text-cyan-400" /> 后端
                </span>
                <span className="text-slate-200">{status.data?.backend}</span>
              </div>
              <div className="mt-1 flex items-center justify-between">
                <span>模型</span>
                <span className="text-slate-200">{status.data?.model ?? "—"}</span>
              </div>
              <div className="mt-1 flex items-center justify-between">
                <span>向量维度</span>
                <span className="text-slate-200">{status.data?.dimension ?? "—"}</span>
              </div>
            </div>

            {pendingKindTotal > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-slate-400">块类型分布</p>
                {(Object.keys(CHUNK_KIND_LABELS) as ChunkKind[]).map((kind) => {
                  const count = status.data?.chunk_kinds?.[kind] ?? 0;
                  const pct = pendingKindTotal ? Math.round((count / pendingKindTotal) * 100) : 0;
                  return (
                    <div key={kind} className="flex items-center gap-3">
                      <span className="w-12 shrink-0 text-xs text-slate-400">{CHUNK_KIND_LABELS[kind]}</span>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-800">
                        <div className="h-full rounded-full bg-cyan-400/70" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="w-14 shrink-0 text-right text-xs tabular-nums text-slate-300">
                        {formatNumber(count)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3">
              <label className="flex cursor-pointer items-start gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={reindexFull}
                  onChange={(event) => setReindexFull(event.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  全量重建（忽略已索引内容）
                  <span className="mt-0.5 block text-xs text-slate-500">
                    勾选后重新计算全部内容向量，适用于更换 embedding 模型或分块参数之后；不勾选则只补索引待处理内容。
                  </span>
                </span>
              </label>
              <button
                type="button"
                className={`${buttonClass} mt-3 w-full sm:w-auto`}
                onClick={() => void triggerReindex()}
                disabled={reindexing}
              >
                <RefreshCw size={16} className={reindexing ? "animate-spin" : ""} />
                {reindexing ? "提交中…" : reindexFull ? "开始全量重建" : "增量索引"}
              </button>
            </div>

            <p className="flex items-start gap-1.5 text-xs text-slate-500">
              <Clock3 size={13} className="mt-0.5 shrink-0" />
              索引任务在 Celery 后台异步执行，进度会反映在上方「已索引」数字中（每 15 秒刷新）。
            </p>
          </div>
        )}
      </Panel>

      <Panel className="p-5">
        <div className="mb-3 flex items-center gap-2">
          <Layers size={16} className="text-cyan-400" />
          <h2 className="font-semibold text-white">说明</h2>
        </div>
        <ul className="list-disc space-y-2 pl-5 text-sm leading-6 text-slate-400">
          <li>
            本地检索对已同步的视频内容（标题 / 描述 / 字幕 / 转写）做向量 + 关键词混合召回，结果按
            RRF 融合排序，命中以「视频」为单位聚合展示。
          </li>
          <li>向量后端不可用时自动降级为纯关键词召回，并如实提示。</li>
          <li>
            在「视频内容搜索」页创建内容搜索计划后，可在「本地语义检索」TAB 中对其执行即时检索；
            重建索引不会中断正在进行的检索。
          </li>
        </ul>
      </Panel>
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "warning";
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3 text-center">
      <p className={`text-lg font-semibold tabular-nums ${tone === "warning" ? "text-amber-300" : "text-white"}`}>
        {value}
      </p>
      <p className="mt-1 text-xs text-slate-500">{label}</p>
    </div>
  );
}
