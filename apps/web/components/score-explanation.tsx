"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Info } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";

// ─── Types ───────────────────────────────────────────────────────────────────

interface ScoreComponent {
  name: string;
  raw_value: number | null;
  percentile: number | null;
  weight: number;
  weighted_contribution: number | null;
  missing: boolean;
  note: string | null;
}

interface ScoreExplanationData {
  entity_id: string;
  entity_type: string;
  score_field: string;
  score_value: number | null;
  algorithm_version: string;
  components: ScoreComponent[];
  missing_fields: string[];
  sample_window: Record<string, string | null>;
  confidence: number | null;
  confidence_reason: string | null;
  metadata: Record<string, unknown>;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function confidenceTone(
  value: number | null,
): "success" | "warning" | "danger" | "neutral" {
  if (value == null) return "neutral";
  if (value >= 0.75) return "success";
  if (value >= 0.45) return "warning";
  return "danger";
}

function confidenceText(value: number | null): string {
  if (value == null) return "未提供";
  return `${Math.round(value * 100)}%`;
}

function formatWindow(window: Record<string, string | null>): string {
  const parts: string[] = [];
  if (window.start)
    parts.push(`开始: ${new Date(window.start).toLocaleString("zh-CN")}`);
  if (window.end)
    parts.push(`结束: ${new Date(window.end).toLocaleString("zh-CN")}`);
  if (window.observed_at)
    parts.push(`观测: ${new Date(window.observed_at).toLocaleString("zh-CN")}`);
  if (window.freshness_basis)
    parts.push(`新鲜度基准: ${window.freshness_basis}`);
  if (window.sample_size) parts.push(`样本量: ${window.sample_size}`);
  return parts.join(" · ") || "—";
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ScoreExplanationPanel({
  entityType,
  entityId,
  apiPath,
  workspaceId,
}: {
  entityType: "video" | "topic" | "event";
  entityId: string;
  apiPath: string;
  workspaceId: string;
}) {
  const [open, setOpen] = useState(false);

  const explanation = useQuery({
    queryKey: [`explain-${entityType}`, entityId, workspaceId],
    queryFn: () => apiRequest<ScoreExplanationData>(apiPath, { workspaceId }),
    enabled: open && Boolean(workspaceId),
  });

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-cyan-400 transition hover:bg-cyan-500/10 hover:text-cyan-300"
      >
        <Info size={12} />
        解释
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>

      {open && (
        <div className="mt-2 rounded-xl border border-slate-800 bg-slate-950/80 p-4">
          {explanation.isLoading && (
            <div className="animate-pulse space-y-2">
              <div className="h-4 w-1/3 rounded bg-slate-800" />
              <div className="h-4 w-2/3 rounded bg-slate-800" />
              <div className="h-4 w-1/2 rounded bg-slate-800" />
            </div>
          )}

          {explanation.error && (
            <p className="text-xs text-rose-400">
              加载失败: {explanation.error.message}
            </p>
          )}

          {explanation.data && (
            <div className="space-y-3">
              {/* Header: algorithm + confidence */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-slate-300">
                  算法: {explanation.data.algorithm_version}
                </span>
                <Badge tone={confidenceTone(explanation.data.confidence)}>
                  置信度 {confidenceText(explanation.data.confidence)}
                </Badge>
                {explanation.data.score_value != null && (
                  <span className="text-xs text-slate-400">
                    最终分:{" "}
                    <span className="font-semibold text-white">
                      {explanation.data.score_value.toFixed(2)}
                    </span>
                  </span>
                )}
              </div>

              {/* Confidence reason */}
              {explanation.data.confidence_reason && (
                <p className="text-[11px] leading-5 text-slate-500">
                  {explanation.data.confidence_reason}
                </p>
              )}

              {/* Components table */}
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-800">
                      <th className="pb-2 text-left font-medium text-slate-500">
                        分量
                      </th>
                      <th className="pb-2 text-right font-medium text-slate-500">
                        原值
                      </th>
                      <th className="pb-2 text-right font-medium text-slate-500">
                        权重
                      </th>
                      <th className="pb-2 text-right font-medium text-slate-500">
                        贡献
                      </th>
                      <th className="pb-2 pl-3 text-left font-medium text-slate-500">
                        权重条
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/50">
                    {explanation.data.components.map((comp) => (
                      <tr
                        key={comp.name}
                        className={comp.missing ? "bg-amber-500/5" : ""}
                      >
                        <td className="py-2">
                          <span
                            className={
                              comp.missing
                                ? "font-medium text-amber-400"
                                : "text-slate-300"
                            }
                          >
                            {comp.name}
                          </span>
                          {comp.missing && (
                            <span className="ml-1.5 rounded bg-amber-500/20 px-1 py-0.5 text-[10px] text-amber-400">
                              缺失
                            </span>
                          )}
                        </td>
                        <td className="py-2 text-right text-slate-400">
                          {comp.raw_value != null
                            ? comp.raw_value.toFixed(2)
                            : "—"}
                        </td>
                        <td className="py-2 text-right text-slate-400">
                          {(comp.weight * 100).toFixed(1)}%
                        </td>
                        <td className="py-2 text-right font-medium text-slate-200">
                          {comp.weighted_contribution != null
                            ? comp.weighted_contribution.toFixed(2)
                            : "—"}
                        </td>
                        <td className="py-2 pl-3">
                          <div className="h-1.5 w-20 rounded-full bg-slate-800">
                            <div
                              className={`h-full rounded-full ${
                                comp.missing
                                  ? "bg-amber-500/50"
                                  : "bg-gradient-to-r from-cyan-500 to-emerald-400"
                              }`}
                              style={{
                                width: `${Math.min(comp.weight * 100 * 2, 100)}%`,
                              }}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Component notes */}
              {explanation.data.components.some((c) => c.note) && (
                <div className="space-y-1">
                  {explanation.data.components
                    .filter((c) => c.note)
                    .map((c) => (
                      <p
                        key={c.name}
                        className={`text-[11px] ${
                          c.missing ? "text-amber-400/80" : "text-slate-500"
                        }`}
                      >
                        • {c.name}: {c.note}
                      </p>
                    ))}
                </div>
              )}

              {/* Missing fields summary */}
              {explanation.data.missing_fields.length > 0 && (
                <div className="rounded-lg border border-amber-800/50 bg-amber-950/30 px-3 py-2">
                  <p className="text-[11px] text-amber-400">
                    缺失字段: {explanation.data.missing_fields.join(", ")}
                  </p>
                </div>
              )}

              {/* Sample window */}
              <div className="flex items-center gap-2 text-[11px] text-slate-500">
                <span className="font-medium text-slate-400">
                  样本时间范围:
                </span>
                <span>{formatWindow(explanation.data.sample_window)}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
