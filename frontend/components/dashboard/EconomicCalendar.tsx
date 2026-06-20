"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

export function EconomicCalendar() {
  const { data } = useQuery({ queryKey: ["calendar"], queryFn: api.calendar });
  const rows = (data ?? []).slice(0, 8);
  return (
    <Card title="Economic Calendar" delay={0.2}>
      {rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">
          Connect FMP_API_KEY to load upcoming events.
        </p>
      ) : (
        <ul className="space-y-2.5">
          {rows.map((e: any, i: number) => (
            <li key={i} className="flex items-center justify-between gap-3 text-sm">
              <div className="min-w-0">
                <p className="truncate text-text/90">{e.event}</p>
                <p className="text-xs text-muted">
                  {e.country} · {String(e.date).slice(0, 16).replace("T", " ")}
                </p>
              </div>
              {e.impact && (
                <Badge tone={e.impact === "High" ? "down" : "neutral"}>{e.impact}</Badge>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
