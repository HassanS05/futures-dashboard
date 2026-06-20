"use client";

import type { ReactNode } from "react";
import { useStream } from "@/lib/ws";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

const WATCH = ["BTCUSD", "ETHUSD", "AAPL", "MSFT", "SPY"];

export function Shell({ children }: { children: ReactNode }) {
  const { connected } = useStream(WATCH);
  return (
    <div className="min-h-screen bg-grid-faint bg-[size:38px_38px]">
      <Sidebar />
      <main className="px-4 pb-16 lg:pl-64 lg:pr-8">
        <Topbar connected={connected} />
        {children}
      </main>
    </div>
  );
}
