"use client";

import { buttonClass, inputClass, secondaryButtonClass } from "@/components/ui";
import { TIME_RANGE_PRESETS } from "@/lib/time-range";

/**
 * Global, reusable time-range selector. Presentational + controlled: the
 * parent owns the URL/local state and computes the `published_from` lower
 * bound via `resolvePublishedFrom`. Presets cover the common windows; an
 * optional custom date field allows precise lower bounds.
 */
export function TimeRangePicker({
  value,
  onChange,
  customFrom,
  onCustomFromChange,
}: {
  value: string;
  onChange: (value: string) => void;
  customFrom?: string;
  onCustomFromChange?: (value: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-slate-500">时间范围</span>
      {TIME_RANGE_PRESETS.map((preset) => (
        <button
          key={preset.key}
          type="button"
          onClick={() => onChange(preset.key)}
          className={
            value === preset.key
              ? `${buttonClass} h-8 px-3 text-xs`
              : `${secondaryButtonClass} h-8 px-3 text-xs`
          }
        >
          {preset.label}
        </button>
      ))}
      {onCustomFromChange && (
        <input
          type="date"
          aria-label="自定义起始日期"
          value={customFrom ?? ""}
          onChange={(event) => onCustomFromChange(event.target.value)}
          className={`${inputClass} h-8 w-auto px-2 text-xs`}
        />
      )}
    </div>
  );
}
