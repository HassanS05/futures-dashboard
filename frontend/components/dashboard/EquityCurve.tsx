"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { fmtCompact, fmtCurrency } from "@/lib/format";

export function EquityCurve() {
  const { data } = useQuery({ queryKey: ["equity"], queryFn: api.equityCurve });
  const series = data ?? [];

  return (
    <Card title="Equity Curve" delay={0.05}>
      {series.length < 2 ? (
        <p className="py-12 text-center text-sm text-muted">
          Building history… the curve fills in as daily snapshots accrue
          ({series.length} day{series.length === 1 ? "" : "s"} so far).
        </p>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 10, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="equity" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3DD7E0" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#3DD7E0" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="day"
                tick={{ fill: "#7A86A1", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                tickFormatter={(v) => fmtCompact(v)}
                tick={{ fill: "#7A86A1", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={48}
              />
              <Tooltip
                contentStyle={{
                  background: "#0E1320",
                  border: "1px solid #1E2638",
                  borderRadius: 12,
                  color: "#E6EAF2",
                }}
                formatter={(v: number) => [fmtCurrency(v), "Value"]}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="#3DD7E0"
                strokeWidth={2}
                fill="url(#equity)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
