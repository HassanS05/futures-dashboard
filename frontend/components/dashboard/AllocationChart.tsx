"use client";

import { useQuery } from "@tanstack/react-query";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";

const COLORS = ["#3DD7E0", "#8B7BFF", "#E8B765", "#2FD08A", "#FF5C72", "#5B4FD6"];

export function AllocationChart() {
  const { data } = useQuery({ queryKey: ["summary"], queryFn: api.portfolioSummary });
  const entries = Object.entries(data?.allocation ?? {});
  const chart = entries.map(([name, value]) => ({ name, value }));

  return (
    <Card title="Asset Allocation" delay={0.05}>
      {chart.length === 0 ? (
        <Empty />
      ) : (
        <div className="flex items-center gap-4">
          <div className="h-40 w-40 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={chart}
                  dataKey="value"
                  innerRadius={48}
                  outerRadius={70}
                  paddingAngle={3}
                  stroke="none"
                >
                  {chart.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="flex-1 space-y-2">
            {chart.map((c, i) => (
              <li key={c.name} className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2 capitalize text-muted">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: COLORS[i % COLORS.length] }}
                  />
                  {c.name}
                </span>
                <span className="stat-num text-text">{c.value.toFixed(1)}%</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function Empty() {
  return (
    <p className="py-10 text-center text-sm text-muted">
      Add positions to see your allocation.
    </p>
  );
}
