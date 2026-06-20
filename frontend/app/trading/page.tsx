"use client";

import { useMutation } from "@tanstack/react-query";
import { Calculator } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Metric } from "@/components/ui/Metric";
import { fmtCurrency } from "@/lib/format";

// Mirrors backend CONTRACTS — the original prototype, now part of HR5 Invest.
const CONTRACTS = [
  "MGC (Micro Gold Futures)",
  "GC (Gold Futures)",
  "MNQ (Micro Nasdaq Futures)",
  "MES (Micro S&P Futures)",
];

export default function TradingPage() {
  const [s, setS] = useState({
    contract: CONTRACTS[0],
    entry_price: 3358,
    tp_price: 3381,
    sl_price: 3350,
    quantity: 1,
  });
  const calc = useMutation({ mutationFn: () => api.futuresCalc(s) as Promise<any> });

  const num = (k: keyof typeof s) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setS({ ...s, [k]: Number(e.target.value) });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Trading · Futures Calculator</h1>
        <p className="text-sm text-muted">
          Risk/reward for MGC · GC · MNQ · MES (ported from the original tool).
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Scenario">
          <div className="space-y-3">
            <label className="block text-sm">
              <span className="text-muted">Contract</span>
              <select
                value={s.contract}
                onChange={(e) => setS({ ...s, contract: e.target.value })}
                className="mt-1 w-full rounded-lg border border-border bg-surface/60 px-3 py-2 focus:border-accent/50 focus:outline-none"
              >
                {CONTRACTS.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            {(
              [
                ["Entry price", "entry_price"],
                ["Take Profit", "tp_price"],
                ["Stop Loss", "sl_price"],
                ["Contracts", "quantity"],
              ] as const
            ).map(([label, key]) => (
              <label key={key} className="block text-sm">
                <span className="text-muted">{label}</span>
                <input
                  type="number"
                  value={s[key]}
                  onChange={num(key)}
                  className="mt-1 w-full rounded-lg border border-border bg-surface/60 px-3 py-2 focus:border-accent/50 focus:outline-none"
                />
              </label>
            ))}
            <button
              onClick={() => calc.mutate()}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent-grad py-2.5 text-sm font-semibold text-canvas"
            >
              <Calculator size={16} /> Calculate
            </button>
          </div>
        </Card>

        <Card title="Result" delay={0.05}>
          {calc.data ? (
            <div className="grid grid-cols-2 gap-5">
              <Metric label="Ticks to TP" value={String(calc.data.ticks_to_tp)} />
              <Metric label="Ticks to SL" value={String(calc.data.ticks_to_sl)} />
              <Metric
                label="Potential Profit"
                value={fmtCurrency(calc.data.potential_profit)}
                tone={1}
              />
              <Metric
                label="Potential Loss"
                value={fmtCurrency(calc.data.potential_loss)}
                tone={-1}
              />
              <Metric
                label="Risk / Reward"
                value={calc.data.risk_reward ? `${calc.data.risk_reward} : 1` : "∞"}
                large
              />
            </div>
          ) : (
            <p className="py-12 text-center text-sm text-muted">
              Enter a scenario and hit Calculate.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
