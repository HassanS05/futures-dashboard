/**
 * Thin typed API client. Calls are proxied to FastAPI via next.config rewrites,
 * so the same relative paths work in dev and prod.
 */
import type {
  AIResponse,
  HeatmapCell,
  PortfolioSummary,
  Quote,
  RiskMetrics,
} from "./types";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  portfolioSummary: () => http<PortfolioSummary>("/api/portfolio/summary"),
  quotes: (symbols: string[]) =>
    http<Quote[]>(`/api/market/quotes?symbols=${symbols.join(",")}`),
  movers: (kind: "gainers" | "losers" | "actives" = "gainers") =>
    http<Quote[]>(`/api/market/movers?kind=${kind}`),
  heatmap: () => http<HeatmapCell[]>("/api/market/heatmap"),
  calendar: () => http<any[]>("/api/market/calendar"),
  news: (tickers?: string[]) =>
    http<any[]>(`/api/market/news${tickers ? `?tickers=${tickers.join(",")}` : ""}`),
  risk: (symbol: string) => http<RiskMetrics>(`/api/analytics/risk/${symbol}`),
  correlations: () => http<{ symbols: string[]; matrix: number[][] }>("/api/analytics/correlations"),
  aiStatus: () => http<{ enabled: boolean; providers: Record<string, boolean> }>("/api/ai/status"),
  ask: (agent: string, prompt: string, context?: object) =>
    http<AIResponse>("/api/ai/ask", {
      method: "POST",
      body: JSON.stringify({ agent, prompt, context }),
    }),
  addPosition: (body: object) =>
    http("/api/portfolio/positions", { method: "POST", body: JSON.stringify(body) }),
  futuresCalc: (body: object) =>
    http("/api/futures/calc", { method: "POST", body: JSON.stringify(body) }),
};
