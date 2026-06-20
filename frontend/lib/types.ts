export interface Quote {
  symbol: string;
  name?: string;
  price: number;
  change: number;
  change_percent: number;
  day_high?: number;
  day_low?: number;
  market_cap?: number;
  volume?: number;
  asset_class: string;
}

export interface PositionValuation {
  id: string;
  symbol: string;
  asset_class: string;
  quantity: number;
  avg_price: number;
  price: number;
  market_value: number;
  cost_basis: number;
  pnl: number;
  pnl_percent: number;
  weight: number;
  source: string;
}

export interface PortfolioSummary {
  total_value: number;
  total_cost: number;
  total_pnl: number;
  total_pnl_percent: number;
  day_pnl: number;
  day_pnl_percent: number;
  positions: PositionValuation[];
  allocation: Record<string, number>;
  updated_at: string;
}

export interface RiskMetrics {
  sharpe_ratio: number | null;
  annualised_volatility: number | null;
  max_drawdown: number | null;
  var_95: number | null;
  best_day: number | null;
  worst_day: number | null;
  win_rate: number | null;
  note?: string;
}

export interface AIResponse {
  agent: string;
  model_used: string;
  provider: string;
  content: string;
  cached: boolean;
}

export interface HeatmapCell {
  sector: string;
  change: number;
}
