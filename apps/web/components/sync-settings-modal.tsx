"use client";

import type {
  AccountRecord,
  AccountSyncSettingsOverride,
  SyncSettingsRecord,
  YtDlpDownloadSettings,
} from "@sio/shared-types";
import { Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { useWorkspace } from "@/components/app-shell";
import {
  DEFAULT_DOWNLOAD_SETTINGS,
  DownloadSettingsFields,
} from "@/components/download-settings-fields";
import { useToast } from "@/components/toast";
import { apiRequest } from "@/lib/browser-api";
import { Badge, buttonClass, secondaryButtonClass } from "@/components/ui";

export function SyncSettingsModal({
  account,
  onClose,
  onSynced,
}: {
  account: AccountRecord;
  onClose: () => void;
  onSynced: () => void | Promise<void>;
}) {
  const { workspaceId } = useWorkspace();
  const { notify } = useToast();
  const [settings, setSettings] =
    useState<YtDlpDownloadSettings>(DEFAULT_DOWNLOAD_SETTINGS);
  const [sourceLabel, setSourceLabel] = useState<string>("默认设置");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!workspaceId) return;
    let cancelled = false;
    (async () => {
      try {
        const [workspace, override] = await Promise.all([
          apiRequest<SyncSettingsRecord>("/settings/sync", {
            workspaceId: workspaceId!,
          }).catch(() => null),
          apiRequest<AccountSyncSettingsOverride | null>(
            `/accounts/${encodeURIComponent(account.id)}/sync-settings`,
            { workspaceId: workspaceId! },
          ).catch(() => null),
        ]);
        if (cancelled) return;
        if (override?.download) {
          setSettings(override.download);
          setSourceLabel("已保存的账号独立设置");
        } else if (workspace?.config.download) {
          setSettings(workspace.config.download);
          setSourceLabel("工作区默认设置");
        }
      } catch {
        // fall back to DEFAULT_DOWNLOAD_SETTINGS already in state
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, account.id]);

  async function confirm() {
    if (!workspaceId) return;
    setBusy(true);
    try {
      await apiRequest<AccountSyncSettingsOverride>(
        `/accounts/${encodeURIComponent(account.id)}/sync-settings`,
        {
          method: "PATCH",
          workspaceId,
          csrf: true,
          body: JSON.stringify({ download: settings }),
        },
      );
      await apiRequest(`/accounts/${encodeURIComponent(account.id)}/sync`, {
        method: "POST",
        workspaceId,
        csrf: true,
      });
      notify("同步任务已排队，本次下载内容已保存为该账号独立配置");
      await onSynced();
      onClose();
    } catch (error) {
      const apiErr = error as { status?: number; code?: string };
      if (apiErr.status === 422 && apiErr.code === "sync_validation_error") {
        notify(
          "该账号当前无法同步，可能适配器尚未实现或账号已停用。",
          "error",
        );
      } else {
        notify(error instanceof Error ? error.message : "同步失败", "error");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        aria-label="关闭"
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-white">同步下载内容</h2>
            <p className="mt-0.5 truncate text-xs text-slate-500">
              {account.display_name} · 选择本次同步要抓取的内容
            </p>
          </div>
          <button
            aria-label="关闭"
            className="grid size-8 shrink-0 place-items-center rounded-lg text-slate-400 hover:bg-slate-800 hover:text-white"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Badge tone="info">{sourceLabel}</Badge>
            <span>每次同步均按此设置抓取，并保存为该账号独立配置</span>
          </div>
          <DownloadSettingsFields value={settings} onChange={setSettings} />
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-slate-800 px-5 py-4">
          <button
            className={secondaryButtonClass}
            onClick={onClose}
            disabled={busy}
          >
            取消
          </button>
          <button className={buttonClass} onClick={confirm} disabled={busy}>
            {busy ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                保存并同步…
              </>
            ) : (
              "保存设置并同步"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
