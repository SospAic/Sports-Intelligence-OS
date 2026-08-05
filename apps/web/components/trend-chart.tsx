"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export function TrendChart({
  data,
  dataKey = "value",
}: {
  data: Array<Record<string, string | number | null>>;
  dataKey?: string;
}) {
  if (!data.length)
    return (
      <div className="grid h-64 place-items-center text-sm text-slate-500">
        尚无趋势快照
      </div>
    );
  return (
    <div className="h-64 w-full" role="img" aria-label="时间序列趋势图">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={data}
          margin={{ left: 0, right: 12, top: 12, bottom: 0 }}
        >
          <defs>
            <linearGradient id="trend" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.28} />
              <stop offset="95%" stopColor="#22d3ee" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            stroke="#1e293b"
            strokeDasharray="3 3"
            vertical={false}
          />
          <XAxis dataKey="name" stroke="#64748b" tick={{ fontSize: 11 }} />
          <YAxis stroke="#64748b" tick={{ fontSize: 11 }} width={58} />
          <Tooltip
            labelFormatter={(_: unknown, payload: unknown) => {
              const first = Array.isArray(payload) ? payload[0] : undefined;
              const timestamp = (
                first as { payload?: { timestamp?: string } } | undefined
              )?.payload?.timestamp;
              return timestamp
                ? new Date(timestamp).toLocaleString("zh-CN")
                : "";
            }}
            contentStyle={{
              background: "#020617",
              border: "1px solid #334155",
              borderRadius: 10,
            }}
          />
          <Area
            type="monotone"
            dataKey={dataKey}
            connectNulls={false}
            stroke="#22d3ee"
            fill="url(#trend)"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
