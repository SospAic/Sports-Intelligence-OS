"use client";

import { usePathname, useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";

/**
 * "返回上一级" button used on detail pages.
 *
 * - When the user arrived via in-app navigation there is browser history, so
 *   we call `router.back()` (preserves list scroll/state).
 * - On a direct/deep-link load there is no history, so we derive the parent
 *   route from the current pathname (stripping the last segment) and push to
 *   it. `fallbackHref` overrides the derived parent when provided.
 */
export function BackButton({
  label = "返回上一级",
  className = "",
  fallbackHref,
}: {
  label?: string;
  className?: string;
  fallbackHref?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();

  const handleClick = () => {
    const hasHistory =
      typeof window !== "undefined" && window.history.length > 1;
    if (hasHistory) {
      router.back();
    } else {
      const derived = pathname.split("/").slice(0, -1).join("/");
      const parent = (fallbackHref ?? derived) || "/";
      router.push(parent);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm font-medium text-slate-200 transition hover:bg-slate-900 ${className}`}
    >
      <ArrowLeft size={15} />
      {label}
    </button>
  );
}
