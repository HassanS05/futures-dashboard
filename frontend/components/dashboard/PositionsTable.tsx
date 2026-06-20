"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { fmtCurrency, fmtPercent, fmtSigned, toneClass } from "@/lib/format";

export function PositionsTable() {
  const { data } = useQuery({ queryKey: ["summary"], queryFn: api.portfolioSummary });
  const rows = data?.positions ?? [];

  return (
    <Card title="Open Positions" delay={0.2}>
      {rows.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted">
          No positions yet — add some from the Portfolio page.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-muted">
                <th className="pb-3 font-medium">Asset</th>
                <th className="pb-3 text-right font-medium">Qty</th>
                <th className="pb-3 text-right font-medium">Avg</th>
                <th className="pb-3 text-right font-medium">Price</th>
                <th className="pb-3 text-right font-medium">Value</th>
                <th className="pb-3 text-right font-medium">P&L</th>
                <th className="pb-3 text-right font-medium">Weight</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {rows.map((p) => (
                <tr key={p.id} className="transition-colors hover:bg-surface-2/40">
                  <td className="py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-text">{p.symbol}</span>
                      <Badge tone="accent">{p.asset_class}</Badge>
                    </div>
                  </td>
                  <td className="stat-num py-3 text-right text-muted">{p.quantity}</td>
                  <td className="stat-num py-3 text-right text-muted">
                    {fmtCurrency(p.avg_price)}
                  </td>
                  <td className="stat-num py-3 text-right">{fmtCurrency(p.price)}</td>
                  <td className="stat-num py-3 text-right">{fmtCurrency(p.market_value)}</td>
                  <td className={`stat-num py-3 text-right ${toneClass(p.pnl)}`}>
                    {fmtSigned(p.pnl)}{" "}
                    <span className="text-xs">({fmtPercent(p.pnl_percent)})</span>
                  </td>
                  <td className="stat-num py-3 text-right text-muted">
                    {p.weight.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
