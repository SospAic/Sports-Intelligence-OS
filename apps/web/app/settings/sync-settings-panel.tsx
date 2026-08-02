"use client";

import type { SyncSettingsRecord } from "@sio/shared-types";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Save } from "lucide-react";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import { Panel, buttonClass, inputClass } from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";

function ymdToDateInput(ymd?: string): string {
  if (!ymd || !/^\d{8}$/.test(ymd)) return "";
  return `${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)}`;
}

function dateInputToYmd(value?: string): string {
  if (!value) return "";
  const clean = value.replace(/-/g, "");
  return /^\d{8}$/.test(clean) ? clean : "";
}

export function SyncSettingsPanel() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const canEdit = ["owner", "admin"].includes(role ?? "");

  const data = useQuery({
    queryKey: ["sync-settings", workspaceId],
    queryFn: () =>
      apiRequest<SyncSettingsRecord>("/settings/sync", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
  });

  const [maxContents, setMaxContents] = useState<string>("");
  const [skipExisting, setSkipExisting] = useState(true);
  const [dateAfter, setDateAfter] = useState("");
  const [dateBefore, setDateBefore] = useState("");
  const [playlistStart, setPlaylistStart] = useState("1");
  const [extraArgs, setExtraArgs] = useState("{}");
  const [pending, setPending] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (hydrated || !data.data) return;
    const cfg = data.data.config;
    setMaxContents(cfg.max_contents != null ? String(cfg.max_contents) : "");
    setSkipExisting(cfg.skip_existing);
    setDateAfter(ymdToDateInput(cfg.yt_dlp.dateafter));
    setDateBefore(ymdToDateInput(cfg.yt_dlp.datebefore));
    setPlaylistStart(String(cfg.yt_dlp.playlist_start ?? 1));
    setExtraArgs(JSON.stringify(cfg.yt_dlp.extra_args ?? {}, null, 2));
    setHydrated(true);
  }, [data.data, hydrated]);

  async function saveSettings(form: FormData) {
    if (!workspaceId) return;
    setPending(true);
    try {
      let parsedExtra: Record<string, unknown> = {};
      const rawExtra = String(form.get("extra_args") ?? "{}").trim();
      if (rawExtra) {
        try {
          const parsed = JSON.parse(rawExtra);
          parsedExtra = parsed && typeof parsed === "object" ? parsed : {};
        } catch {
          notify("附加参数（extra_args）不是合法 JSON", "error");
          return;
        }
      }
      const body = {
        config: {
          max_contents: maxContents.trim() ? Number(maxContents) : null,
          skip_existing: skipExisting,
          yt_dlp: {
            dateafter: dateInputToYmd(dateAfter),
            datebefore: dateInputToYmd(dateBefore),
            playlist_start: Number(playlistStart) || 1,
            extra_args: parsedExtra,
          },
        },
      };
      await apiRequest("/settings/sync", {
        method: "PUT",
        workspaceId,
        csrf: true,
        body: JSON.stringify(body),
      });
      notify("同步设置已保存");
      setHydrated(false);
      await queryClient.invalidateQueries({ queryKey: ["sync-settings"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "保存失败", "error");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-5">
      <Panel className="p-5">
        <h2 className="font-medium text-white">同步与抓取策略</h2>
        <p className="mt-1 text-xs text-slate-500">
          统一控制本工作区所有账号的抓取行为。同步默认拉取账号的<strong>全部历史作品</strong>
          （全量抓取）；下方参数用于限定范围、量级与重复处理方式。
        </p>
      </Panel>
      {data.isLoading && (
        <Panel className="p-5 text-sm text-slate-500">正在加载同步设置…</Panel>
      )}
      {data.error && (
        <Panel className="p-5 text-sm text-rose-400">
          同步设置加载失败：{data.error.message}
        </Panel>
      )}
      {data.data && (
        <Panel className="p-5">
          <form action={saveSettings} className="grid gap-4">
            <label className="grid gap-2 text-sm">
              单次同步最多抓取作品数
              <input
                name="max_contents"
                className={inputClass}
                type="number"
                min="1"
                max="5000"
                value={maxContents}
                onChange={(e) => setMaxContents(e.target.value)}
                placeholder="留空 = 全量抓取（受分页上限约束）"
                disabled={!canEdit}
              />
            </label>
            <div className="grid grid-cols-2 gap-4">
              <label className="grid gap-2 text-sm">
                仅抓取此日期之后（dateafter）
                <input
                  name="dateafter"
                  className={inputClass}
                  type="date"
                  value={dateAfter}
                  onChange={(e) => setDateAfter(e.target.value)}
                  disabled={!canEdit}
                />
              </label>
              <label className="grid gap-2 text-sm">
                仅抓取此日期之前（datebefore）
                <input
                  name="datebefore"
                  className={inputClass}
                  type="date"
                  value={dateBefore}
                  onChange={(e) => setDateBefore(e.target.value)}
                  disabled={!canEdit}
                />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <label className="grid gap-2 text-sm">
                播放列表起始位置（playlist_start）
                <input
                  name="playlist_start"
                  className={inputClass}
                  type="number"
                  min="1"
                  value={playlistStart}
                  onChange={(e) => setPlaylistStart(e.target.value)}
                  disabled={!canEdit}
                />
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  name="skip_existing"
                  type="checkbox"
                  checked={skipExisting}
                  onChange={(e) => setSkipExisting(e.target.checked)}
                  disabled={!canEdit}
                />
                已存在的作品跳过更新（仅刷新指标，不覆盖标题 / 封面）
              </label>
            </div>
            <label className="grid gap-2 text-sm">
              额外 yt-dlp 参数（extra_args，JSON）
              <textarea
                name="extra_args"
                className={`${inputClass} min-h-24 font-mono text-xs`}
                value={extraArgs}
                onChange={(e) => setExtraArgs(e.target.value)}
                placeholder={'{\n  "match_filter": "...",\n  "geo_bypass": true\n}'}
                disabled={!canEdit}
              />
            </label>
            <p className="text-xs text-slate-500">
              行业实践：用日期区间缩小范围、控制单次量级可显著降低被限流与超时风险；同步间隔请在账号的「同步周期」中设置。留空字段表示不施加该限制。
            </p>
            {canEdit && (
              <button className={`${buttonClass} w-full justify-center`} disabled={pending}>
                <Save size={14} />
                {pending ? "保存中…" : "保存同步设置"}
              </button>
            )}
          </form>
        </Panel>
      )}
      <Panel className="p-5">
        <h3 className="flex items-center gap-2 font-medium text-slate-200">
          <RefreshCw size={14} className="text-cyan-400" />
          抓取逻辑说明
        </h3>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-xs leading-5 text-slate-400">
          <li>默认对每个账号执行<strong>全量抓取</strong>，不再区分增量与全量；历史作品会被一并拉取回填。</li>
          <li>「单次同步最多抓取作品数」为空时，抓取受平台分页上限约束；设置数值可硬性限制单次量级。</li>
          <li>遇到已存在的作品时，由「已存在的作品跳过更新」决定是跳过还是覆盖可编辑字段（指标始终刷新）。</li>
          <li>日期区间（dateafter / datebefore）以 YYYYMMDD 形式传给 yt-dlp，用于限定作品时间范围。</li>
        </ul>
      </Panel>
    </div>
  );
}
