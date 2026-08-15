"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { ExternalImage } from "@/components/external-image";
import { StatePanel } from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import {
  ContentCalendarResponse,
  ContentRecord,
  ContentRecordPage,
} from "@sio/shared-types";
import { formatDate, formatNumber } from "@/lib/format";
import { contentCoverUrl } from "@/lib/media";

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

function buildDayPath(
  date: string,
  platform: string,
  query: string,
): string {
  const params = new URLSearchParams();
  params.set("published_from", `${date}T00:00:00Z`);
  params.set("published_to", `${date}T23:59:59.999999Z`);
  params.set("page_size", "100");
  params.set("sort", "view_count");
  params.set("order", "desc");
  if (platform) params.set("platform", platform);
  if (query) params.set("query", query);
  return `/contents?${params.toString()}`;
}

export function ContentCalendar({
  platform = "",
  query = "",
}: {
  platform?: string;
  query?: string;
}) {
  const { workspaceId } = useWorkspace();
  const today = new Date();
  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth() + 1);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const calendar = useQuery({
    queryKey: [
      "content-calendar",
      workspaceId,
      viewYear,
      viewMonth,
      platform,
      query,
    ],
    queryFn: () =>
      apiRequest<ContentCalendarResponse>(
        `/contents/calendar?year=${viewYear}&month=${viewMonth}${
          platform ? `&platform=${encodeURIComponent(platform)}` : ""
        }${query ? `&query=${encodeURIComponent(query)}` : ""}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });

  const dayDetail = useQuery({
    queryKey: ["content-calendar-day", workspaceId, selectedDate, platform, query],
    queryFn: () =>
      apiRequest<ContentRecordPage>(buildDayPath(selectedDate!, platform, query), {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && Boolean(selectedDate),
  });

  const bucketsByDate = useMemo(() => {
    const map = new Map<string, { count: number; total_views: number }>();
    for (const b of calendar.data?.buckets ?? []) {
      map.set(b.date, { count: b.count, total_views: b.total_views });
    }
    return map;
  }, [calendar.data]);

  const maxCount = useMemo(() => {
    let max = 0;
    for (const b of calendar.data?.buckets ?? []) max = Math.max(max, b.count);
    return max || 1;
  }, [calendar.data]);

  const grid = useMemo(() => {
    const firstWeekday = (new Date(viewYear, viewMonth - 1, 1).getDay() + 6) % 7;
    const daysInMonth = new Date(viewYear, viewMonth, 0).getDate();
    const cells: (number | null)[] = [];
    for (let i = 0; i < firstWeekday; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) cells.push(d);
    return cells;
  }, [viewYear, viewMonth]);

  function shiftMonth(delta: number) {
    let m = viewMonth + delta;
    let y = viewYear;
    if (m < 1) {
      m = 12;
      y -= 1;
    } else if (m > 12) {
      m = 1;
      y += 1;
    }
    setViewMonth(m);
    setViewYear(y);
    setSelectedDate(null);
  }

  if (calendar.isLoading) {
    return (
      <div className="rounded-2xl border border-slate-800 p-10 text-center text-slate-500">
        正在加载内容日历…
      </div>
    );
  }
  if (calendar.error) {
    return (
      <StatePanel
        type="error"
        title="日历加载失败"
        detail={calendar.error.message}
        onRetry={() => calendar.refetch()}
      />
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            className="rounded-lg border border-slate-700 p-2 text-slate-300 hover:bg-slate-800"
            onClick={() => shiftMonth(-1)}
            aria-label="上个月"
          >
            <ChevronLeft size={16} />
          </button>
          <h2 className="min-w-28 text-center text-lg font-semibold text-slate-100">
            {viewYear} 年 {viewMonth} 月
          </h2>
          <button
            className="rounded-lg border border-slate-700 p-2 text-slate-300 hover:bg-slate-800"
            onClick={() => shiftMonth(1)}
            aria-label="下个月"
          >
            <ChevronRight size={16} />
          </button>
        </div>
        <div className="flex items-center gap-4 text-sm text-slate-400">
          <span>
            本月作品 <b className="text-slate-100">{calendar.data?.total_count ?? 0}</b> 条
          </span>
          <span>
            累计播放{" "}
            <b className="text-slate-100">
              {formatNumber(calendar.data?.total_views ?? 0)}
            </b>
          </span>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-slate-800">
        <div className="grid grid-cols-7 border-b border-slate-800 bg-slate-950/60">
          {WEEKDAYS.map((w) => (
            <div
              key={w}
              className="px-2 py-2 text-center text-xs font-medium text-slate-500"
            >
              {w}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7">
          {grid.map((day, idx) => {
            if (day === null) {
              return (
                <div
                  key={`empty-${idx}`}
                  className="min-h-24 border-b border-r border-slate-800/60 bg-slate-950/30"
                />
              );
            }
            const isoDate = `${viewYear}-${String(viewMonth).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
            const bucket = bucketsByDate.get(isoDate);
            const count = bucket?.count ?? 0;
            const intensity = count > 0 ? Math.max(0.12, count / maxCount) : 0;
            const isSelected = selectedDate === isoDate;
            return (
              <button
                key={isoDate}
                type="button"
                disabled={count === 0}
                onClick={() => setSelectedDate(isoDate)}
                style={{
                  backgroundColor:
                    count > 0
                      ? `rgba(34,211,238,${intensity.toFixed(3)})`
                      : undefined,
                }}
                className={`flex min-h-24 flex-col items-start gap-1 border-b border-r border-slate-800/60 p-2 text-left transition ${
                  count > 0
                    ? "hover:bg-cyan-400/20"
                    : "cursor-default bg-slate-950/30"
                } ${isSelected ? "ring-2 ring-inset ring-cyan-400" : ""}`}
              >
                <span
                  className={`text-sm ${
                    count > 0 ? "text-slate-100" : "text-slate-600"
                  }`}
                >
                  {day}
                </span>
                {count > 0 && (
                  <span className="rounded-full bg-slate-950/70 px-2 py-0.5 text-xs font-medium text-cyan-100">
                    {count} 条
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {selectedDate && (
        <div className="rounded-2xl border border-slate-800 bg-slate-950/50 p-5">
          <div className="mb-4 flex items-center gap-2 text-slate-200">
            <CalendarDays size={16} className="text-cyan-300" />
            <span className="font-medium">{selectedDate} 发布的作品</span>
            {dayDetail.data && (
              <span className="text-sm text-slate-500">
                （共 {dayDetail.data.total} 条）
              </span>
            )}
          </div>
          {dayDetail.isLoading ? (
            <p className="text-sm text-slate-500">加载中…</p>
          ) : dayDetail.error ? (
            <StatePanel
              type="error"
              title="当日作品加载失败"
              detail={dayDetail.error.message}
              onRetry={() => dayDetail.refetch()}
            />
          ) : (
            <ul className="divide-y divide-slate-800">
              {(dayDetail.data?.items ?? []).map((item: ContentRecord) => (
                <li
                  key={item.id}
                  className="flex items-center gap-3 py-3 first:pt-0 last:pb-0"
                >
                  <ExternalImage
                    src={contentCoverUrl(item)}
                    alt=""
                    className="h-12 w-20 shrink-0 rounded-md object-cover"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-1 font-medium text-slate-100">
                      {item.title}
                    </p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {item.platform.name} · 发布于{" "}
                      {formatDate(item.published_at)}
                    </p>
                  </div>
                  <div className="shrink-0 text-right text-xs text-slate-400">
                    <div>
                      播放{" "}
                      <span className="text-slate-200">
                        {formatNumber(item.latest_snapshot?.view_count)}
                      </span>
                    </div>
                    <div>
                      点赞{" "}
                      <span className="text-slate-200">
                        {formatNumber(item.latest_snapshot?.like_count)}
                      </span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
