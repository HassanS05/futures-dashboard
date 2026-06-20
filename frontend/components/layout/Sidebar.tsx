"use client";

import {
  LayoutDashboard,
  Wallet,
  LineChart,
  Bot,
  BarChart3,
  CandlestickChart,
  Bell,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/portfolio", label: "Portfolio", icon: Wallet },
  { href: "/markets", label: "Markets", icon: LineChart },
  { href: "/trading", label: "Trading", icon: CandlestickChart },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/copilot", label: "AI Copilot", icon: Bot },
];

export function Sidebar() {
  const path = usePathname();
  return (
    <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col border-r border-border bg-surface/40 px-4 py-6 backdrop-blur-xl lg:flex">
      <Link href="/" className="mb-8 flex items-center gap-2 px-2">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-accent-grad font-bold text-canvas">
          H5
        </div>
        <div>
          <p className="text-sm font-semibold leading-none">HR5 Invest</p>
          <p className="text-[10px] uppercase tracking-widest text-muted">Copilot</p>
        </div>
      </Link>

      <nav className="flex flex-1 flex-col gap-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all",
                active
                  ? "bg-surface-2 text-text shadow-glow"
                  : "text-muted hover:bg-surface-2/60 hover:text-text",
              )}
            >
              <Icon
                size={18}
                className={cn(active ? "text-accent" : "text-muted group-hover:text-text")}
              />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="glass-2 mt-4 p-3 text-xs text-muted">
        <p className="mb-1 font-medium text-text">Read-only & secure</p>
        Never stores seed phrases or private keys.
      </div>
    </aside>
  );
}
