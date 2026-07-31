"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { secondaryButtonClass } from "@/components/ui";

export function Pagination({
  page,
  total,
  pageSize,
  onPageChange,
}: {
  page: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1 && total <= pageSize) return null;
  return (
    <nav
      aria-label="分页导航"
      className="flex items-center justify-center gap-3"
    >
      <button
        aria-label="上一页"
        className={`${secondaryButtonClass} h-9 px-3`}
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        <ChevronLeft size={15} />
        上一页
      </button>
      <span
        aria-live="polite"
        className="min-w-32 text-center text-sm text-slate-400"
      >
        第 {page} 页 / 共 {pages} 页
      </span>
      <button
        aria-label="下一页"
        className={`${secondaryButtonClass} h-9 px-3`}
        disabled={page >= pages}
        onClick={() => onPageChange(page + 1)}
      >
        下一页
        <ChevronRight size={15} />
      </button>
    </nav>
  );
}
