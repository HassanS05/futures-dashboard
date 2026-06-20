"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { fmtCurrency } from "@/lib/format";

export default function AlertsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["alerts"], queryFn: api.alerts, refetchInterval: 10_000 });
  const [form, setForm] = useState({ symbol: "", direction: "above", target: "" });

  const create = useMutation({
    mutationFn: () =>
      api.createAlert({
        symbol: form.symbol.toUpperCase(),
        direction: form.direction,
        target: Number(form.target),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alerts"] });
      setForm({ symbol: "", direction: "above", target: "" });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteAlert(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Alerts</h1>
        <p className="text-sm text-muted">
          Price thresholds — evaluated live and pushed over WebSocket.
        </p>
      </div>

      <Card title="New Alert">
        <div className="grid gap-3 sm:grid-cols-4">
          <input
            placeholder="Symbol (e.g. BTCUSD)"
            value={form.symbol}
            onChange={(e) => setForm({ ...form, symbol: e.target.value })}
            className="rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm focus:border-accent/50 focus:outline-none"
          />
          <select
            value={form.direction}
            onChange={(e) => setForm({ ...form, direction: e.target.value })}
            className="rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm focus:border-accent/50 focus:outline-none"
          >
            <option value="above">Price above</option>
            <option value="below">Price below</option>
          </select>
          <input
            placeholder="Target price"
            type="number"
            value={form.target}
            onChange={(e) => setForm({ ...form, target: e.target.value })}
            className="rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm focus:border-accent/50 focus:outline-none"
          />
          <button
            onClick={() => create.mutate()}
            disabled={!form.symbol || !form.target || create.isPending}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-accent-grad px-4 py-2 text-sm font-semibold text-canvas disabled:opacity-40"
          >
            <Plus size={15} /> Create
          </button>
        </div>
      </Card>

      <Card title="Active & Triggered" delay={0.05}>
        {!data?.length ? (
          <div className="flex items-center gap-3 py-8 text-muted">
            <Bell className="text-accent" /> No alerts yet.
          </div>
        ) : (
          <ul className="divide-y divide-border/60">
            {data.map((a: any) => (
              <li key={a.id} className="flex items-center justify-between py-3">
                <div className="flex items-center gap-3">
                  <Badge tone={a.triggered_at ? "down" : "accent"}>
                    {a.triggered_at ? "triggered" : "active"}
                  </Badge>
                  <span className="text-sm">
                    <span className="font-medium">{a.symbol}</span>{" "}
                    <span className="text-muted">
                      {a.direction} {fmtCurrency(a.target)}
                    </span>
                  </span>
                </div>
                <button
                  onClick={() => remove.mutate(a.id)}
                  className="text-muted transition-colors hover:text-down"
                >
                  <Trash2 size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
