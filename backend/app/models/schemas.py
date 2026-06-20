"""Pydantic models shared across the API (request/response contracts)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AssetClass(str, Enum):
    crypto = "crypto"
    stock = "stock"
    etf = "etf"
    forex = "forex"
    commodity = "commodity"
    cash = "cash"


class Quote(BaseModel):
    symbol: str
    name: str | None = None
    price: float
    change: float = 0.0
    change_percent: float = 0.0
    day_high: float | None = None
    day_low: float | None = None
    market_cap: float | None = None
    volume: float | None = None
    asset_class: AssetClass = AssetClass.stock


class Position(BaseModel):
    id: str | None = None
    symbol: str
    asset_class: AssetClass = AssetClass.crypto
    quantity: float = Field(gt=0)
    avg_price: float = Field(ge=0)
    source: str = "manual"  # manual | cex | dex | broker (read-only label)


class PositionValuation(Position):
    price: float = 0.0
    market_value: float = 0.0
    cost_basis: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    weight: float = 0.0


class Transaction(BaseModel):
    id: str | None = None
    symbol: str
    side: str  # buy | sell
    quantity: float
    price: float
    fee: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    note: str | None = None


class PortfolioSummary(BaseModel):
    total_value: float
    total_cost: float
    total_pnl: float
    total_pnl_percent: float
    day_pnl: float
    day_pnl_percent: float
    positions: list[PositionValuation]
    allocation: dict[str, float]  # asset_class -> weight %
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RiskMetrics(BaseModel):
    sharpe_ratio: float | None = None
    annualised_volatility: float | None = None
    max_drawdown: float | None = None
    var_95: float | None = None
    best_day: float | None = None
    worst_day: float | None = None
    win_rate: float | None = None
    note: str | None = None


class FuturesScenario(BaseModel):
    contract: str
    entry_price: float
    tp_price: float
    sl_price: float
    quantity: int = Field(ge=1)


class FuturesResult(BaseModel):
    contract: str
    ticks_to_tp: int
    ticks_to_sl: int
    potential_profit: float
    potential_loss: float
    risk_reward: float | None


class Alert(BaseModel):
    id: str | None = None
    symbol: str
    direction: str = "above"  # above | below
    target: float
    note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    triggered_at: datetime | None = None


class AIAgent(str, Enum):
    portfolio = "portfolio"
    dca = "dca"
    research = "research"
    market = "market"
    journal = "journal"


class AIRequest(BaseModel):
    agent: AIAgent
    prompt: str
    context: dict | None = None
    model_override: str | None = None


class AIResponse(BaseModel):
    agent: AIAgent
    model_used: str
    provider: str
    content: str
    cached: bool = False
