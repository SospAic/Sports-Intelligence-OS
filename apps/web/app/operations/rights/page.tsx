"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";

type RightsStatus = "unknown" | "pending_review" | "approved" | "restricted" | "expired";
type RightsItem = {
  id: string | null;
  artifact_id: string;
  artifact_kind: string;
  file_name: string;
  artifact_status: string;
  rights_status: RightsStatus;
  license_type: string | null;
  rights_holder: string | null;
  territories: string[];
  valid_until: string | null;
  evidence_url: string | null;
  evidence_note: string | null;
  source_kind: "live" | "imported";
  updated_at: string;
};
type RightsPage = { items: RightsItem[]; total: number };

const statusLabels: Record<RightsStatus, string> = {
  unknown: "未核验",
  pending_review: "待审核",
  approved: "已批准",
  restricted: "受限",
  expired: "已过期",
};

function statusTone(status: RightsStatus): "neutral" | "warning" | "success" | "danger" {
  if (status === "approved") return "success";
  if (status === "restricted" || status === "expired") return "danger";
  if (status === "pending_review") return "warning";
  return "neutral";
}

export default function MediaRightsPage() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<RightsItem | null>(null);
  const [rightsStatus, setRightsStatus] = useState<RightsStatus>("pending_review");
  const [licenseType, setLicenseType] = useState("");
  const [rightsHolder, setRightsHolder] = useState("");
  const [territories, setTerritories] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [evidenceUrl, setEvidenceUrl] = useState("");
  const [evidenceNote, setEvidenceNote] = useState("");
  const [sourceKind, setSourceKind] = useState<"live" | "imported">("imported");
  const canEdit = ["owner", "admin", "editor"].includes(role ?? "");
  const query = useQuery({
    queryKey: ["media-rights", workspaceId, status],
    queryFn: () =>
      apiRequest<RightsPage>(
        `/storage/rights?page=1&page_size=100${status ? `&rights_status=${status}` : ""}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });

  const selectItem = (item: RightsItem) => {
    setSelected(item);
    setRightsStatus(item.rights_status === "unknown" ? "pending_review" : item.rights_status);
    setLicenseType(item.license_type ?? "");
    setRightsHolder(item.rights_holder ?? "");
    setTerritories(item.territories.join(", "));
    setValidUntil(item.valid_until?.slice(0, 10) ?? "");
    setEvidenceUrl(item.evidence_url ?? "");
    setEvidenceNote(item.evidence_note ?? "");
    setSourceKind(item.source_kind);
  };

  const update = useMutation({
    mutationFn: () =>
      apiRequest<RightsItem>(`/storage/artifacts/${selected?.artifact_id}/rights`, {
        method: "PATCH",
        workspaceId: workspaceId!,
        csrf: true,
        body: JSON.stringify({
          rights_status: rightsStatus,
          license_type: licenseType || null,
          rights_holder: rightsHolder || null,
          territories: territories.split(",").map((item) => item.trim()).filter(Boolean),
          valid_until: validUntil ? new Date(`${validUntil}T23:59:59Z`).toISOString() : null,
          evidence_url: evidenceUrl || null,
          evidence_note: evidenceNote || null,
          source_kind: sourceKind,
        }),
      }),
    onSuccess: async (item) => {
      notify("素材权利状态已保存");
      selectItem(item);
      await queryClient.invalidateQueries({ queryKey: ["media-rights", workspaceId] });
    },
    onError: (error: Error) => notify(error.message || "素材权利保存失败", "error"),
  });

  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Rights"
        title="素材权利中心"
        description="可搜到不等于可商用；为每个已登记素材保留许可、地域、有效期、证据和审核状态。"
        actions={
          <select className={inputClass} value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">全部状态</option>
            {Object.entries(statusLabels).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        }
      />
      <Panel className="border-amber-900/40 bg-amber-950/10 p-4 text-sm text-amber-100">
        权利信息由用户或获准 Provider 提供，系统不会根据下载成功、公开可见或搜索命中自动推断可商用。批准状态仍需保留证据链接或许可类型。
      </Panel>
      {query.isLoading ? (
        <Panel className="p-5"><SkeletonRows /></Panel>
      ) : query.error ? (
        <StatePanel type="error" title="素材权利加载失败" detail={query.error.message} />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
          <Panel className="overflow-hidden">
            <div className="border-b border-slate-800 px-5 py-4 text-sm text-slate-400">
              {query.data?.total ?? 0} 个已登记素材 / 未登记项也会显示为“未核验”
            </div>
            <div className="divide-y divide-slate-800">
              {(query.data?.items ?? []).map((item) => (
                <button
                  key={item.artifact_id}
                  type="button"
                  onClick={() => selectItem(item)}
                  className={`flex w-full items-start justify-between gap-4 px-5 py-4 text-left transition hover:bg-slate-900/70 ${selected?.artifact_id === item.artifact_id ? "bg-cyan-950/20" : ""}`}
                >
                  <span className="min-w-0">
                    <span className="flex items-center gap-2 text-sm font-medium text-white">
                      <ShieldCheck size={15} className="text-cyan-300" />
                      <span className="truncate">{item.file_name}</span>
                    </span>
                    <span className="mt-1 block text-xs text-slate-500">
                      {item.artifact_kind} · 物理状态 {item.artifact_status} · 更新 {formatDate(item.updated_at)}
                    </span>
                  </span>
                  <Badge tone={statusTone(item.rights_status)}>{statusLabels[item.rights_status]}</Badge>
                </button>
              ))}
              {!query.data?.items.length && <p className="px-5 py-10 text-sm text-slate-500">暂无已登记媒体；下载或字幕生成完成后，素材会进入这里。</p>}
            </div>
          </Panel>
          <Panel className="p-5">
            <h2 className="text-sm font-semibold text-white">权利审核</h2>
            {!selected ? (
              <p className="mt-4 text-sm text-slate-500">选择左侧素材开始登记许可证据。</p>
            ) : (
              <div className="mt-4 space-y-4">
                <p className="truncate text-xs text-slate-500" title={selected.file_name}>{selected.file_name}</p>
                <label className="block text-xs text-slate-400">审核状态<select className={`${inputClass} mt-1 w-full`} value={rightsStatus} onChange={(event) => setRightsStatus(event.target.value as RightsStatus)} disabled={!canEdit}><option value="pending_review">待审核</option><option value="approved">已批准</option><option value="restricted">受限</option><option value="expired">已过期</option><option value="unknown">未核验</option></select></label>
                <label className="block text-xs text-slate-400">许可类型<input className={`${inputClass} mt-1 w-full`} value={licenseType} onChange={(event) => setLicenseType(event.target.value)} disabled={!canEdit} placeholder="例如：自有、CC BY、授权采购" /></label>
                <label className="block text-xs text-slate-400">权利人<input className={`${inputClass} mt-1 w-full`} value={rightsHolder} onChange={(event) => setRightsHolder(event.target.value)} disabled={!canEdit} /></label>
                <label className="block text-xs text-slate-400">地域（逗号分隔）<input className={`${inputClass} mt-1 w-full`} value={territories} onChange={(event) => setTerritories(event.target.value)} disabled={!canEdit} placeholder="CN, US" /></label>
                <label className="block text-xs text-slate-400">有效期至<input type="date" className={`${inputClass} mt-1 w-full`} value={validUntil} onChange={(event) => setValidUntil(event.target.value)} disabled={!canEdit} /></label>
                <label className="block text-xs text-slate-400">证据链接<input type="url" className={`${inputClass} mt-1 w-full`} value={evidenceUrl} onChange={(event) => setEvidenceUrl(event.target.value)} disabled={!canEdit} placeholder="https://..." /></label>
                <label className="block text-xs text-slate-400">审核备注<textarea className={`${inputClass} mt-1 min-h-24 w-full`} value={evidenceNote} onChange={(event) => setEvidenceNote(event.target.value)} disabled={!canEdit} /></label>
                <label className="block text-xs text-slate-400">信息来源<select className={`${inputClass} mt-1 w-full`} value={sourceKind} onChange={(event) => setSourceKind(event.target.value as "live" | "imported")} disabled={!canEdit}><option value="imported">用户导入</option><option value="live">Provider 实时</option></select></label>
                {canEdit ? <button type="button" className={buttonClass} onClick={() => update.mutate()} disabled={update.isPending}>{update.isPending ? "保存中…" : "保存权利信息"}</button> : <button type="button" className={secondaryButtonClass} disabled>当前角色不可编辑</button>}
              </div>
            )}
          </Panel>
        </div>
      )}
    </main>
  );
}
