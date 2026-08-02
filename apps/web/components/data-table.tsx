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
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  ChevronUp,
} from "lucide-react";
import { useRef, useState, type Dispatch, type SetStateAction } from "react";

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
  virtualized = false,
  virtualHeight = 560,
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
  /** Render all rows in a windowed scroll area instead of paginated pages. */
  virtualized?: boolean;
  /** Scroll viewport height in px when `virtualized` is true. */
  virtualHeight?: number;
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

  const rowHeight = density === "compact" ? 38 : 52;
  const scrollRef = useRef<HTMLDivElement>(null);
  const rows = table.getRowModel().rows;
  const colCount = table.getVisibleLeafColumns().length;

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 10,
    enabled: virtualized,
  });

  const pages = Math.max(1, Math.ceil(total / pageSize));

  const virtualItems = virtualizer.getVirtualItems();
  const firstItem = virtualItems[0];
  const lastItem = virtualItems[virtualItems.length - 1];
  const paddingTop = firstItem ? firstItem.start : 0;
  const paddingBottom =
    firstItem && lastItem ? virtualizer.getTotalSize() - lastItem.end : 0;

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/70">
      <p className="border-b border-slate-800 px-4 py-2 text-[11px] text-slate-500 md:hidden">
        表格可左右滑动查看全部字段
      </p>
      <div
        ref={virtualized ? scrollRef : undefined}
        className={virtualized ? "overflow-auto" : "overflow-x-auto"}
        style={virtualized ? { height: virtualHeight } : undefined}
      >
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
            {rows.length === 0 ? (
              <tr>
                <td colSpan={colCount}>
                  <div className="grid min-h-40 place-items-center text-sm text-slate-500">
                    {empty}
                  </div>
                </td>
              </tr>
            ) : virtualized ? (
              <>
                {paddingTop > 0 && (
                  <tr aria-hidden>
                    <td colSpan={colCount} style={{ height: paddingTop, padding: 0, border: 0 }} />
                  </tr>
                )}
                {virtualItems.map((vi) => {
                  const row = rows[vi.index];
                  if (!row) return null;
                  return (
                    <tr
                      className="hover:bg-slate-900/60"
                      key={row.id}
                      style={{ height: rowHeight }}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td
                          className={`whitespace-nowrap px-4 align-middle text-slate-300 ${density === "compact" ? "py-1.5" : "py-3"}`}
                          key={cell.id}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  );
                })}
                {paddingBottom > 0 && (
                  <tr aria-hidden>
                    <td colSpan={colCount} style={{ height: paddingBottom, padding: 0, border: 0 }} />
                  </tr>
                )}
              </>
            ) : (
              rows.map((row) => (
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
              ))
            )}
          </tbody>
        </table>
      </div>
      {!virtualized && !data.length && (
        <div className="grid min-h-40 place-items-center text-sm text-slate-500">
          {empty}
        </div>
      )}
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 px-4 py-3 text-xs text-slate-400">
        <span>
          {virtualized
            ? `虚拟滚动 · 共 ${total} 条`
            : `共 ${total} 条 · 第 ${page}/${pages} 页`}
        </span>
        {!virtualized && (
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
        )}
      </footer>
    </div>
  );
}
