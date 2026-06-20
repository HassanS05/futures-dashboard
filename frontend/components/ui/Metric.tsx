"use client";

import { cn } from "@/lib/cn";
import { toneClass } from "@/lib/format";

export function Metric({
  label,
  value,
  delta,
  tone,
  large,
}: {
  label: string;
  value: string;
  delta?: string;
  tone?: number;
  large?: boolean;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wider text-muted">{label}</p>
      <p
        className={cn(
          "stat-num mt-1 font-semibold text-text",
          large ? "text-3xl" : "text-xl",
        )}
      >
        {value}
      </p>
      {delta !== undefined && (
        <p className={cn("stat-num mt-0.5 text-sm", toneClass(tone ?? 0))}>{delta}</p>
      )}
    </div>
  );
}
