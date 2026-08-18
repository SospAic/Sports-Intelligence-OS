"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

interface MultiSelectProps {
  label: string;
  options: string[];
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  className?: string;
}

/**
 * Compact multi-select with a checkbox popover. Self-contained (no external
 * UI lib). Closes on outside click. Used for the works-data tag filter and the
 * download page platform/format pickers.
 */
export function MultiSelect({
  label,
  options,
  value,
  onChange,
  placeholder = "全部",
  className = "",
}: MultiSelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  function toggle(option: string) {
    if (value.includes(option)) {
      onChange(value.filter((v) => v !== option));
    } else {
      onChange([...value, option]);
    }
  }

  const summary =
    value.length === 0
      ? placeholder
      : value.length <= 2
        ? value.join("、")
        : `已选 ${value.length} 项`;

  return (
    <div className={`relative ${className}`} ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-left text-sm text-slate-200 hover:border-slate-600"
      >
        <span className="truncate">
          <span className="mr-1 text-slate-500">{label}</span>
          {summary}
        </span>
        <ChevronDown size={15} className="shrink-0 text-slate-500" />
      </button>
      {open && (
        <div className="absolute z-30 mt-1 max-h-64 w-full overflow-auto rounded-xl border border-slate-700 bg-slate-900 p-1 shadow-xl">
          {options.length === 0 && (
            <div className="px-3 py-2 text-sm text-slate-500">暂无选项</div>
          )}
          {options.map((option) => {
            const checked = value.includes(option);
            return (
              <button
                type="button"
                key={option}
                onClick={() => toggle(option)}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm text-slate-200 hover:bg-slate-800"
              >
                <span
                  className={`flex h-4 w-4 items-center justify-center rounded border ${
                    checked
                      ? "border-cyan-400 bg-cyan-500/20 text-cyan-300"
                      : "border-slate-600"
                  }`}
                >
                  {checked && <Check size={12} />}
                </span>
                <span className="truncate">{option}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
