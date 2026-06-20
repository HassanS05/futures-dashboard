"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { fmtCurrency } from "@/lib/format";

export function RecentTransactions() {
  const { data } = useQuery({ queryKey: ["transactions"], queryFn: () => api.transactions(8) });
  const rows = data ?? [];
  return (
    <Card title="Recent Transactions" delay={0.15}>
      {rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">No transactions logged yet.</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((t) => (
            <li key={t.id} className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2">
                <Badge tone={t.side === "buy" ? "up" : "down"}>{t.side}</Badge>
                <span className="font-medium">{t.symbol}</span>
              </span>
              <span className="stat-num text-muted">
                {t.quantity} @ {fmtCurrency(t.price)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
