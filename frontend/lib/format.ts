export const fmtCurrency = (n: number, max = 2) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: max,
  }).format(n ?? 0);

export const fmtCompact = (n: number) =>
  new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(
    n ?? 0,
  );

export const fmtPercent = (n: number) =>
  `${n >= 0 ? "+" : ""}${(n ?? 0).toFixed(2)}%`;

export const fmtSigned = (n: number) =>
  `${n >= 0 ? "+" : "-"}${fmtCurrency(Math.abs(n ?? 0))}`;

export const toneClass = (n: number) =>
  n > 0 ? "text-up" : n < 0 ? "text-down" : "text-muted";
