"use client";

import { Search, Wifi, WifiOff } from "lucide-react";

export function Topbar({ connected }: { connected: boolean }) {
  return (
    <header className="sticky top-0 z-10 mb-6 flex items-center justify-between gap-4 border-b border-border/60 bg-canvas/70 px-1 py-4 backdrop-blur-xl">
      <div className="relative w-full max-w-md">
        <Search
          size={16}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
        />
        <input
          placeholder="Search markets, assets, tickers…"
          className="w-full rounded-xl border border-border bg-surface/60 py-2 pl-9 pr-3 text-sm text-text placeholder:text-muted focus:border-accent/50 focus:outline-none focus:ring-1 focus:ring-accent/40"
        />
      </div>
      <div className="flex items-center gap-3">
        <span
          className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${
            connected ? "bg-up/10 text-up" : "bg-surface-2 text-muted"
          }`}
        >
          {connected ? <Wifi size={13} /> : <WifiOff size={13} />}
          {connected ? "Live" : "Connecting"}
        </span>
        <div className="grid h-9 w-9 place-items-center rounded-full bg-violet/20 text-sm font-semibold text-violet">
          H5
        </div>
      </div>
    </header>
  );
}
