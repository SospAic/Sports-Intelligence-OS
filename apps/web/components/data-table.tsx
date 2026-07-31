"use client";

import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type VisibilityState,
} from "@tanstack/react-table";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  ChevronUp,
} from "lucide-react";
import { useState, type Dispatch, type SetStateAction } from "react";

import { secondaryButtonClass } from "@/components/ui";

export function DataTable<T>({
  data,
  columns,
  total,
  page,
  pageSize,
  onPageChange,
  empty = "暂无数据",
  getRowId,
  columnVisibility,
  onColumnVisibilityChange,
  density = "comfortable",
  stickyHeader = false,
}: {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  total: number;
  page: number;
  pageSize: number;
  onPageChange?: (page: number) => void;
  empty?: string;
  getRowId?: (row: T) => string;
  columnVisibility?: VisibilityState;
  onColumnVisibilityChange?: Dispatch<SetStateAction<VisibilityState>>;
  density?: "compact" | "comfortable";
  stickyHeader?: boolean;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  // TanStack Table intentionally exposes stateful function references; rows are not passed to memoized children.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    state: { sorting, columnVisibility },
    onSortingChange: setSorting,
    onColumnVisibilityChange,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId,
  });
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/70">
      <p className="border-b border-slate-800 px-4 py-2 text-[11px] text-slate-500 md:hidden">
        表格可左右滑动查看全部字段
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1100px] text-left text-sm">
          <caption className="sr-only">数据表，共 {total} 条记录</caption>
          <thead
            className={`border-b border-slate-800 bg-slate-900/60 text-xs text-slate-400 ${stickyHeader ? "sticky top-0 z-10 bg-slate-900" : ""}`}
          >
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => (
                  <th
                    className="whitespace-nowrap px-4 py-3 font-medium"
                    key={header.id}
                    aria-sort={
                      header.column.getIsSorted() === "asc"
                        ? "ascending"
                        : header.column.getIsSorted() === "desc"
                          ? "descending"
                          : "none"
                    }
                  >
                    {header.isPlaceholder ? null : (
                      <button
                        className="inline-flex items-center gap-1"
                        onClick={header.column.getToggleSortingHandler()}
                        disabled={!header.column.getCanSort()}
                      >
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                        {header.column.getCanSort() &&
                          (header.column.getIsSorted() === "asc" ? (
                            <ChevronUp size={13} />
                          ) : header.column.getIsSorted() === "desc" ? (
                            <ChevronDown size={13} />
                          ) : (
                            <ChevronsUpDown
                              size={13}
                              className="text-slate-600"
                            />
                          ))}
                      </button>
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-800">
            {table.getRowModel().rows.map((row) => (
              <tr className="hover:bg-slate-900/60" key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td
                    className={`whitespace-nowrap px-4 align-middle text-slate-300 ${density === "compact" ? "py-1.5" : "py-3"}`}
                    key={cell.id}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!data.length && (
        <div className="grid min-h-40 place-items-center text-sm text-slate-500">
          {empty}
        </div>
      )}
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 px-4 py-3 text-xs text-slate-400">
        <span>
          共 {total} 条 · 第 {page}/{pages} 页
        </span>
        <div className="flex gap-2">
          <button
            className={`${secondaryButtonClass} h-8 px-2`}
            disabled={page <= 1}
            onClick={() => onPageChange?.(page - 1)}
          >
            <ChevronLeft size={15} />
            上一页
          </button>
          <button
            className={`${secondaryButtonClass} h-8 px-2`}
            disabled={page >= pages}
            onClick={() => onPageChange?.(page + 1)}
          >
            下一页
            <ChevronRight size={15} />
          </button>
        </div>
      </footer>
    </div>
  );
}
