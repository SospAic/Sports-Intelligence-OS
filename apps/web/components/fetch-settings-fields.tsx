"use client";

import type { AccountSyncFetchSettings } from "@sio/shared-types";
import { inputClass } from "@/components/ui";

export const DEFAULT_FETCH_SETTINGS: AccountSyncFetchSettings = {
  max_contents: null,
  dateafter: null,
  datebefore: null,
  playlist_start: null,
};

/** YYYYMMDD -> YYYY-MM-DD for <input type="date">. */
function toDateInput(value: string | null): string {
  if (!value || !/^\d{8}$/.test(value)) return "";
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}

/** YYYY-MM-DD -> YYYYMMDD (or null when empty). */
function fromDateInput(value: string): string | null {
  const compact = value.replace(/-/g, "");
  return /^\d{8}$/.test(compact) ? compact : null;
}

type Props = {
  value: AccountSyncFetchSettings;
  onChange: (next: AccountSyncFetchSettings) => void;
  disabled?: boolean;
};

export function FetchSettingsFields({ value, onChange, disabled }: Props) {
  function setField<K extends keyof AccountSyncFetchSettings>(
    key: K,
    v: AccountSyncFetchSettings[K],
  ) {
    onChange({ ...value, [key]: v });
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="grid gap-2 text-sm">
          单次抓取数量
          <input
            type="number"
            min={1}
            className={inputClass}
            value={value.max_contents ?? ""}
            disabled={disabled}
            placeholder="0 = 全量抓取"
            onChange={(event) =>
              setField(
                "max_contents",
                event.target.value === ""
                  ? null
                  : Math.max(1, Number(event.target.value) || 0),
              )
            }
          />
          <span className="text-xs text-slate-500">
            限制本次同步抓取的作品条数，留空/0 表示全量
          </span>
        </label>
        <label className="grid gap-2 text-sm">
          起始位置（跳过前 N 条）
          <input
            type="number"
            min={1}
            className={inputClass}
            value={value.playlist_start ?? ""}
            disabled={disabled}
            placeholder="从头开始"
            onChange={(event) =>
              setField(
                "playlist_start",
                event.target.value === ""
                  ? null
                  : Math.max(1, Number(event.target.value) || 1),
              )
            }
          />
          <span className="text-xs text-slate-500">
            从目录的第 N 条开始抓取（用于增量续抓）
          </span>
        </label>
        <label className="grid gap-2 text-sm">
          抓取范围（起始日期）
          <input
            type="date"
            className={inputClass}
            value={toDateInput(value.dateafter)}
            disabled={disabled}
            onChange={(event) =>
              setField("dateafter", fromDateInput(event.target.value))
            }
          />
          <span className="text-xs text-slate-500">只抓取该日期之后发布的作品</span>
        </label>
        <label className="grid gap-2 text-sm">
          抓取范围（截止日期）
          <input
            type="date"
            className={inputClass}
            value={toDateInput(value.datebefore)}
            disabled={disabled}
            onChange={(event) =>
              setField("datebefore", fromDateInput(event.target.value))
            }
          />
          <span className="text-xs text-slate-500">只抓取该日期之前发布的作品</span>
        </label>
      </div>
    </div>
  );
}
