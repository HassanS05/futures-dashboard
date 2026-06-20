"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { MarketHeatmap } from "@/components/dashboard/MarketHeatmap";
import { fmtCurrency, fmtPercent, toneClass } from "@/lib/format";

function Movers({ kind, title }: { kind: "gainers" | "losers"; title: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["movers", kind],
    queryFn: () => api.movers(kind),
    refetchInterval: 20_000,
  });
  return (
    <Card title={title}>
      <div className="space-y-1">
        {isLoading &&
          Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-9" />)}
        {data?.slice(0, 8).map((q) => (
          <div key={q.symbol} className="flex items-center justify-between py-1.5 text-sm">
            <span className="font-medium">{q.symbol}</span>
            <span className="flex items-center gap-3">
              <span className="stat-num text-muted">{fmtCurrency(q.price)}</span>
              <span className={`stat-num ${toneClass(q.change_percent)}`}>
                {fmtPercent(q.change_percent)}
              </span>
            </span>
          </div>
        ))}
        {!isLoading && !data?.length && (
          <p className="py-6 text-center text-sm text-muted">No data.</p>
        )}
      </div>
    </Card>
  );
}

function News() {
  const { data } = useQuery({ queryKey: ["news"], queryFn: () => api.news() });
  return (
    <Card title="Market News" delay={0.1}>
      <div className="space-y-3">
        {(data ?? []).slice(0, 6).map((n: any, i: number) => (
          <a
            key={i}
            href={n.url}
            target="_blank"
            rel="noreferrer"
            className="block border-b border-border/50 pb-3 last:border-0"
          >
            <p className="text-sm text-text/90 hover:text-accent">{n.title}</p>
            <p className="text-xs text-muted">{n.site}</p>
          </a>
        ))}
        {!data?.length && <p className="py-6 text-center text-sm text-muted">No news.</p>}
      </div>
    </Card>
  );
}

export default function MarketsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Markets</h1>
      <div className="grid gap-6 lg:grid-cols-2">
        <Movers kind="gainers" title="Top Gainers" />
        <Movers kind="losers" title="Top Losers" />
      </div>
      <MarketHeatmap />
      <News />
    </div>
  );
}
