import { AlertTriangle, Inbox, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  status,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  status?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="grid gap-4 border-b border-slate-800/80 pb-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-xs font-semibold tracking-[.22em] text-cyan-400 uppercase">
            {eyebrow}
          </p>
        )}
        <h1
          className="mt-1 min-w-0 truncate text-2xl font-semibold tracking-tight text-white lg:text-3xl"
          title={title}
        >
          {title}
        </h1>
        {description && (
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
            {description}
          </p>
        )}
        {status && <div className="mt-3">{status}</div>}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 lg:flex-nowrap">
          {actions}
        </div>
      )}
    </header>
  );
}

export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`surface-card rounded-2xl border border-slate-800 bg-slate-950/70 shadow-sm ${className}`}
    >
      {children}
    </section>
  );
}

export function SettingsGroup({
  title,
  description,
  children,
  tone = "cyan",
  className = "",
}: {
  title: string;
  description?: string;
  children: ReactNode;
  tone?: "cyan" | "violet" | "amber" | "slate";
  className?: string;
}) {
  const tones = {
    cyan: "border-cyan-900/70 bg-cyan-950/10 text-cyan-200",
    violet: "border-violet-900/70 bg-violet-950/10 text-violet-200",
    amber: "border-amber-900/70 bg-amber-950/10 text-amber-200",
    slate: "border-slate-700/80 bg-slate-900/30 text-slate-200",
  };
  return (
    <fieldset
      className={`min-w-0 rounded-xl border p-4 transition-colors ${tones[tone]} ${className}`}
    >
      <legend className="px-2 text-sm font-semibold">{title}</legend>
      {description && (
        <p className="mb-4 text-xs leading-5 text-slate-500">{description}</p>
      )}
      {children}
    </fieldset>
  );
}

export function MetricCard({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
}) {
  return (
    <Panel className="p-5">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <p className="min-w-0 truncate whitespace-nowrap text-xs text-slate-400 sm:text-sm" title={label}>
          {label}
        </p>
        <span className="shrink-0 text-cyan-400">{icon}</span>
      </div>
      <p className="mt-4 truncate text-2xl font-semibold tabular-nums text-white">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </Panel>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
}) {
  const colors = {
    neutral: "border-slate-700 bg-slate-900 text-slate-300",
    success: "border-emerald-800 bg-emerald-950/50 text-emerald-300",
    warning: "border-amber-800 bg-amber-950/50 text-amber-300",
    danger: "border-rose-800 bg-rose-950/50 text-rose-300",
    info: "border-cyan-800 bg-cyan-950/50 text-cyan-300",
  };
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs transition-colors ${colors[tone]}`}
    >
      {children}
    </span>
  );
}

export function StatePanel({
  type,
  title,
  detail,
  action,
  onRetry,
}: {
  type: "empty" | "error";
  title: string;
  detail?: string;
  action?: ReactNode;
  onRetry?: () => void;
}) {
  const Icon = type === "error" ? AlertTriangle : Inbox;
  return (
    <div className="grid min-h-56 place-items-center p-8 text-center">
      <div>
        <Icon
          className={`mx-auto ${type === "error" ? "text-rose-400" : "text-slate-500"}`}
          size={28}
        />
        <h2 className="mt-3 font-medium text-slate-100">{title}</h2>
        {detail && (
          <p className="mt-2 max-w-lg text-sm text-slate-400">{detail}</p>
        )}
        {action && <div className="mt-4">{action}</div>}
        {onRetry && (
          <button
            className="mt-4 inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-900"
            onClick={onRetry}
          >
            <RotateCcw size={14} />
            重试
          </button>
        )}
      </div>
    </div>
  );
}

export function SkeletonRows({ count = 5 }: { count?: number }) {
  return (
    <div className="animate-pulse space-y-3 p-5">
      {Array.from({ length: count }, (_, index) => (
        <div className="h-12 rounded-xl bg-slate-800/70" key={index} />
      ))}
    </div>
  );
}

export const inputClass =
  "h-10 rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20";
export const buttonClass =
  "inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50";
export const secondaryButtonClass =
  "inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-4 text-sm font-medium text-slate-200 transition hover:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-50";
export const dangerButtonClass =
  "inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-red-600 px-4 text-sm font-medium text-white transition hover:bg-red-500 active:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50";

export function Tooltip({
  label,
  children,
  side = "top",
}: {
  label: string;
  children: ReactNode;
  side?: "top" | "bottom";
}) {
  return (
    <span className="group/tooltip relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute z-50 hidden whitespace-nowrap rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-200 shadow-xl group-hover/tooltip:block ${
          side === "top"
            ? "bottom-full left-1/2 mb-2 -translate-x-1/2"
            : "top-full left-1/2 mt-2 -translate-x-1/2"
        }`}
      >
        {label}
      </span>
    </span>
  );
}
