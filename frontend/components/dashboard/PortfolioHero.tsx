"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import { fmtCurrency, fmtPercent, fmtSigned, toneClass } from "@/lib/format";
import { useStream } from "@/lib/ws";

const PERFS = [
  { label: "Day", key: "day" },
  { label: "Week", key: "week" },
  { label: "Month", key: "month" },
  { label: "Year", key: "year" },
];

export function PortfolioHero() {
  const { data } = useQuery({ queryKey: ["summary"], queryFn: api.portfolioSummary });
  const { data: live } = useStream([]);

  // Prefer the live stream value when present; fall back to REST snapshot.
  const total = live?.portfolio?.total_value ?? data?.total_value ?? 0;
  const dayPnl = live?.portfolio?.day_pnl ?? data?.day_pnl ?? 0;
  const dayPct = live?.portfolio?.day_pnl_percent ?? data?.day_pnl_percent ?? 0;
  const totalPnl = data?.total_pnl ?? 0;
  const totalPct = data?.total_pnl_percent ?? 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      className="glass relative overflow-hidden p-6"
    >
      <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-accent/10 blur-3xl" />
      <div className="relative flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="text-xs uppercase tracking-widest text-muted">
            Total Portfolio Value
          </p>
          <p className="stat-num mt-1 text-4xl font-semibold md:text-5xl">
            {fmtCurrency(total)}
          </p>
          <p className={`stat-num mt-2 text-sm ${toneClass(dayPnl)}`}>
            {fmtSigned(dayPnl)} ({fmtPercent(dayPct)}) today
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-widest text-muted">All-time P&L</p>
          <p className={`stat-num mt-1 text-2xl font-semibold ${toneClass(totalPnl)}`}>
            {fmtSigned(totalPnl)}
          </p>
          <p className={`stat-num text-sm ${toneClass(totalPct)}`}>{fmtPercent(totalPct)}</p>
        </div>
      </div>

      <div className="relative mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {PERFS.map((p) => {
          // Day is live; others are placeholders until the history service
          // is wired (documented in ROADMAP).
          const val = p.key === "day" ? dayPct : 0;
          return (
            <div key={p.key} className="glass-2 px-4 py-3">
              <p className="text-[11px] uppercase tracking-wider text-muted">{p.label}</p>
              <p className={`stat-num mt-0.5 text-base ${toneClass(val)}`}>
                {p.key === "day" ? fmtPercent(val) : "—"}
              </p>
            </div>
          );
        })}
      </div>
    </motion.div>
  );
}
