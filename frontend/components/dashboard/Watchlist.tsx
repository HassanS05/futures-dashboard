"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { fmtCurrency, fmtPercent, toneClass } from "@/lib/format";

const SYMBOLS = ["BTCUSD", "ETHUSD", "SOLUSD", "AAPL", "NVDA", "MSFT", "SPY", "QQQ"];

export function Watchlist() {
  const { data, isLoading } = useQuery({
    queryKey: ["watchlist"],
    queryFn: () => api.quotes(SYMBOLS),
    refetchInterval: 10_000,
  });

  return (
    <Card title="Watchlist" delay={0.1} className="h-full">
      <div className="space-y-1">
        {isLoading &&
          Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton h-9 w-full" />
          ))}
        {data?.map((q) => (
          <div
            key={q.symbol}
            className="flex items-center justify-between rounded-lg px-2 py-2 transition-colors hover:bg-surface-2/60"
          >
            <div>
              <p className="text-sm font-medium text-text">{q.symbol}</p>
              <p className="truncate text-xs text-muted">{q.name ?? q.asset_class}</p>
            </div>
            <div className="text-right">
              <p className="stat-num text-sm text-text">{fmtCurrency(q.price)}</p>
              <p className={`stat-num text-xs ${toneClass(q.change_percent)}`}>
                {fmtPercent(q.change_percent)}
              </p>
            </div>
          </div>
        ))}
        {!isLoading && !data?.length && (
          <p className="py-8 text-center text-sm text-muted">
            Connect FMP_API_KEY to stream live quotes.
          </p>
        )}
      </div>
    </Card>
  );
}
