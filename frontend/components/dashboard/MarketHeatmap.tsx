"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";

// Map a sector % move to a green/red intensity.
function cellStyle(change: number) {
  const intensity = Math.min(Math.abs(change) / 3, 1);
  const base = change >= 0 ? "47, 208, 138" : "255, 92, 114";
  return { background: `rgba(${base}, ${0.12 + intensity * 0.5})` };
}

export function MarketHeatmap() {
  const { data, isLoading } = useQuery({
    queryKey: ["heatmap"],
    queryFn: api.heatmap,
    refetchInterval: 30_000,
  });

  return (
    <Card title="Market Heatmap — Sectors" delay={0.15}>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {isLoading &&
          Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton h-16" />
          ))}
        {data?.map((c) => (
          <div
            key={c.sector}
            style={cellStyle(c.change)}
            className="flex flex-col justify-between rounded-xl border border-border/50 p-3"
          >
            <span className="truncate text-xs text-text/90">{c.sector}</span>
            <span className="stat-num text-sm font-semibold">
              {c.change >= 0 ? "+" : ""}
              {c.change.toFixed(2)}%
            </span>
          </div>
        ))}
        {!isLoading && !data?.length && (
          <p className="col-span-full py-8 text-center text-sm text-muted">
            Sector data unavailable.
          </p>
        )}
      </div>
    </Card>
  );
}
