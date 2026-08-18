"use client";

import type {
  AccountRecord,
  AccountSyncSettingsOverride,
  YtDlpDownloadSettings,
} from "@sio/shared-types";
import { Loader2, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useWorkspace } from "@/components/app-shell";
import {
  DEFAULT_DOWNLOAD_SETTINGS,
  DownloadSettingsFields,
} from "@/components/download-settings-fields";
import { useToast } from "@/components/toast";
import { ApiError, apiRequest } from "@/lib/browser-api";
import { buttonClass, inputClass, secondaryButtonClass } from "@/components/ui";

const DOWNLOAD_DEFAULTS_KEY = "sio-account-download-defaults";

function readLocalDownloadDefaults(): YtDlpDownloadSettings {
  if (typeof window === "undefined") return DEFAULT_DOWNLOAD_SETTINGS;
  try {
    const raw = window.localStorage.getItem(DOWNLOAD_DEFAULTS_KEY);
    if (!raw) return DEFAULT_DOWNLOAD_SETTINGS;
    return { ...DEFAULT_DOWNLOAD_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_DOWNLOAD_SETTINGS;
  }
}

function writeLocalDownloadDefaults(d: YtDlpDownloadSettings) {
  try {
    window.localStorage.setItem(DOWNLOAD_DEFAULTS_KEY, JSON.stringify(d));
  } catch {
    // localStorage unavailable; ignore
  }
}

/**
 * Add-account popup that adapts to the visible viewport.
 *
 * Mirrors the viewport-adaptive pattern used by SyncSettingsModal:
 * a centered, scrollable card constrained to `max-h-[90vh]` so it never
 * overflows the screen on small devices. Esc or backdrop click closes it.
 */
export function AddAccountModal({
  onClose,
  onCreated,
  onDuplicate,
}: {
  onClose: () => void;
  onCreated: () => void | Promise<void>;
  /** Called when the server rejects the new account as a duplicate (HTTP 409). */
  onDuplicate?: (externalId: string) => void;
}) {
  const { workspaceId } = useWorkspace();
  const { notify } = useToast();
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  const [externalId, setExternalId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [downloadDefaults, setDownloadDefaults] =
    useState<YtDlpDownloadSettings>(() => readLocalDownloadDefaults());
  const [syncImmediately, setSyncImmediately] = useState(true);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit() {
    if (!workspaceId) return;
    const trimmed = externalId.trim();
    if (!trimmed) {
      notify("请填写账号主页网址", "error");
      return;
    }
    setPending(true);
    try {
      const created = await apiRequest<AccountRecord>("/accounts", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          external_id: trimmed,
          display_name: displayName.trim() || null,
          metadata: {},
        }),
      });
      // Persist the chosen download policy as this account's per-account sync
      // override and remember it locally for the next add.
      await apiRequest<AccountSyncSettingsOverride>(
        `/accounts/${encodeURIComponent(created.id)}/sync-settings`,
        {
          method: "PATCH",
          workspaceId,
          csrf: true,
          body: JSON.stringify({ download: downloadDefaults }),
        },
      ).catch(() => null);
      writeLocalDownloadDefaults(downloadDefaults);
      // Optionally trigger a real sync right after the account is created.
      let syncQueued = true;
      if (syncImmediately) {
        syncQueued = await apiRequest(
          `/accounts/${encodeURIComponent(created.id)}/sync`,
          {
            method: "POST",
            workspaceId,
            csrf: true,
          },
        )
          .then(() => true)
          .catch(() => false);
      }
      notify(
        syncImmediately
          ? syncQueued
            ? "账号已添加并触发同步；真实数据将在同步完成后出现。"
            : "账号已添加，但立即同步未能启动（适配器可能尚未实现或账号已停用），你可稍后在账号行手动同步。"
          : "账号已添加；默认下载设置已保存，真实数据将在同步成功后出现。",
      );
      await client.invalidateQueries({ queryKey: ["accounts"] });
      await onCreated();
      onClose();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        // Account already exists — bubble + list highlight are handled by the
        // parent (the toast already renders bottom-right by design).
        notify("该账号已存在，已在监控列表中定位", "error");
        onDuplicate?.(trimmed);
        onClose();
      } else {
        notify(error instanceof Error ? error.message : "添加失败", "error");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-account-modal-title"
    >
      <button
        aria-label="关闭"
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
          <div className="min-w-0">
            <h2 id="add-account-modal-title" className="text-sm font-semibold text-white">
              添加监控账号
            </h2>
            <p className="mt-0.5 truncate text-xs text-slate-500">
              粘贴账号主页网址，系统将自动识别平台
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
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs text-slate-400">
                账号主页网址
              </span>
              <input
                value={externalId}
                onChange={(event) => setExternalId(event.target.value)}
                required
                className={inputClass}
                placeholder="如 https://youtube.com/@xxx、https://tiktok.com/@xxx"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-slate-400">
                显示名称（可选，同步后自动获取）
              </span>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                className={inputClass}
                placeholder="显示名称（可选）"
              />
            </label>
          </div>

          <div className="space-y-3 rounded-xl border border-slate-800 p-4">
            <div>
              <h3 className="text-sm font-medium text-slate-200">
                下载内容默认设置
              </h3>
              <p className="mt-0.5 text-xs text-slate-500">
                为该账号设置默认的同步下载内容；保存后也会被记录，下次添加账号时自动沿用。
              </p>
            </div>
            <DownloadSettingsFields
              value={downloadDefaults}
              onChange={setDownloadDefaults}
            />
          </div>

          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={syncImmediately}
              onChange={(event) => setSyncImmediately(event.target.checked)}
              className="size-4 rounded border-slate-600 bg-slate-900 accent-cyan-500"
            />
            添加后立即同步（创建账号后立刻触发一次真实数据同步）
          </label>

          <p className="text-xs text-slate-500">
            只需粘贴账号主页网址，系统会自动识别平台（YouTube / TikTok / 抖音 /
            Bilibili），无需手动选择。添加账号不会伪造统计数据；只有 Adapter
            同步成功后才会写入真实快照。
          </p>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-800 px-5 py-4">
          <button
            className={secondaryButtonClass}
            onClick={onClose}
            disabled={pending}
          >
            取消
          </button>
          <button className={buttonClass} onClick={submit} disabled={pending}>
            {pending ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                保存中…
              </>
            ) : (
              <>
                <Plus size={15} />
                保存账号
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
