"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Metric } from "@/components/ui/Metric";
import { PositionsTable } from "@/components/dashboard/PositionsTable";
import { fmtCurrency, fmtPercent } from "@/lib/format";

const ASSET_CLASSES = ["crypto", "stock", "etf", "forex", "commodity"];

export default function PortfolioPage() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["summary"], queryFn: api.portfolioSummary });
  const [form, setForm] = useState({
    symbol: "",
    asset_class: "crypto",
    quantity: "",
    avg_price: "",
  });

  const add = useMutation({
    mutationFn: () =>
      api.addPosition({
        symbol: form.symbol.toUpperCase(),
        asset_class: form.asset_class,
        quantity: Number(form.quantity),
        avg_price: Number(form.avg_price),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["summary"] });
      setForm({ symbol: "", asset_class: "crypto", quantity: "", avg_price: "" });
    },
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Portfolio</h1>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <Metric label="Total Value" value={fmtCurrency(data?.total_value ?? 0)} large />
        </Card>
        <Card delay={0.05}>
          <Metric
            label="Total P&L"
            value={fmtCurrency(data?.total_pnl ?? 0)}
            delta={fmtPercent(data?.total_pnl_percent ?? 0)}
            tone={data?.total_pnl ?? 0}
            large
          />
        </Card>
        <Card delay={0.1}>
          <Metric
            label="Day P&L"
            value={fmtCurrency(data?.day_pnl ?? 0)}
            delta={fmtPercent(data?.day_pnl_percent ?? 0)}
            tone={data?.day_pnl ?? 0}
            large
          />
        </Card>
      </div>

      <Card title="Add Position" delay={0.15}>
        <div className="grid gap-3 sm:grid-cols-5">
          <input
            placeholder="Symbol (e.g. BTCUSD)"
            value={form.symbol}
            onChange={(e) => setForm({ ...form, symbol: e.target.value })}
            className="rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm focus:border-accent/50 focus:outline-none"
          />
          <select
            value={form.asset_class}
            onChange={(e) => setForm({ ...form, asset_class: e.target.value })}
            className="rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm capitalize focus:border-accent/50 focus:outline-none"
          >
            {ASSET_CLASSES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <input
            placeholder="Quantity"
            type="number"
            value={form.quantity}
            onChange={(e) => setForm({ ...form, quantity: e.target.value })}
            className="rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm focus:border-accent/50 focus:outline-none"
          />
          <input
            placeholder="Avg price"
            type="number"
            value={form.avg_price}
            onChange={(e) => setForm({ ...form, avg_price: e.target.value })}
            className="rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm focus:border-accent/50 focus:outline-none"
          />
          <button
            onClick={() => add.mutate()}
            disabled={!form.symbol || !form.quantity || !form.avg_price || add.isPending}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-accent-grad px-4 py-2 text-sm font-semibold text-canvas disabled:opacity-40"
          >
            <Plus size={15} /> Add
          </button>
        </div>
      </Card>

      <PositionsTable />
    </div>
  );
}
