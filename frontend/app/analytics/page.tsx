"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Metric } from "@/components/ui/Metric";

function CorrelationMatrix() {
  const { data } = useQuery({ queryKey: ["correlations"], queryFn: api.correlations });
  if (!data?.symbols?.length)
    return (
      <p className="py-8 text-center text-sm text-muted">
        Hold at least two assets to compute correlations.
      </p>
    );
  const color = (v: number) => {
    const intensity = Math.abs(v);
    const base = v >= 0 ? "61,215,224" : "255,92,114";
    return `rgba(${base}, ${0.1 + intensity * 0.6})`;
  };
  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th className="p-2" />
            {data.symbols.map((s) => (
              <th key={s} className="p-2 text-muted">
                {s}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.matrix.map((row, i) => (
            <tr key={i}>
              <td className="p-2 text-muted">{data.symbols[i]}</td>
              {row.map((v, j) => (
                <td key={j} className="p-1">
                  <div
                    style={{ background: color(v) }}
                    className="stat-num grid h-9 w-12 place-items-center rounded"
                  >
                    {v.toFixed(2)}
                  </div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AnalyticsPage() {
  const [symbol, setSymbol] = useState("BTCUSD");
  const [query, setQuery] = useState("BTCUSD");
  const { data: risk } = useQuery({
    queryKey: ["risk", query],
    queryFn: () => api.risk(query),
  });

  const m = (v: number | null | undefined, suffix = "") =>
    v === null || v === undefined ? "—" : `${v}${suffix}`;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>

      <Card
        title="Risk Metrics"
        action={
          <div className="flex gap-2">
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="w-28 rounded-lg border border-border bg-surface/60 px-3 py-1.5 text-sm focus:border-accent/50 focus:outline-none"
            />
            <button
              onClick={() => setQuery(symbol)}
              className="rounded-lg bg-surface-2 px-3 py-1.5 text-sm hover:bg-surface-2/70"
            >
              Analyze
            </button>
          </div>
        }
      >
        {risk?.note ? (
          <p className="py-6 text-center text-sm text-muted">{risk.note}</p>
        ) : (
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            <Metric label="Sharpe" value={m(risk?.sharpe_ratio)} />
            <Metric label="Volatility" value={m(risk?.annualised_volatility, "%")} />
            <Metric label="Max Drawdown" value={m(risk?.max_drawdown, "%")} tone={-1} />
            <Metric label="VaR 95%" value={m(risk?.var_95, "%")} tone={-1} />
            <Metric label="Best Day" value={m(risk?.best_day, "%")} tone={1} />
            <Metric label="Worst Day" value={m(risk?.worst_day, "%")} tone={-1} />
            <Metric label="Win Rate" value={m(risk?.win_rate, "%")} />
          </div>
        )}
      </Card>

      <Card title="Correlation Matrix — Holdings" delay={0.1}>
        <CorrelationMatrix />
      </Card>
    </div>
  );
}
