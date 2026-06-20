"""Quantitative analytics engine.

Pure functions over price/return series — no I/O — so they're trivially
testable. Implements the classic risk stats: Sharpe, volatility, max drawdown,
VaR and a correlation matrix.
"""

from __future__ import annotations

import numpy as np

from app.models.schemas import RiskMetrics

_TRADING_DAYS = 252


def daily_returns(prices: list[float]) -> np.ndarray:
    arr = np.asarray(prices, dtype=float)
    if arr.size < 2:
        return np.array([])
    return np.diff(arr) / arr[:-1]


def sharpe_ratio(returns: np.ndarray, risk_free: float = 0.0) -> float | None:
    if returns.size < 2 or returns.std() == 0:
        return None
    excess = returns.mean() - risk_free / _TRADING_DAYS
    return float(excess / returns.std() * np.sqrt(_TRADING_DAYS))


def annualised_volatility(returns: np.ndarray) -> float | None:
    if returns.size < 2:
        return None
    return float(returns.std() * np.sqrt(_TRADING_DAYS) * 100)


def max_drawdown(prices: list[float]) -> float | None:
    arr = np.asarray(prices, dtype=float)
    if arr.size < 2:
        return None
    running_max = np.maximum.accumulate(arr)
    drawdowns = (arr - running_max) / running_max
    return float(drawdowns.min() * 100)


def value_at_risk(returns: np.ndarray, confidence: float = 0.95) -> float | None:
    if returns.size < 2:
        return None
    return float(np.percentile(returns, (1 - confidence) * 100) * 100)


def compute_risk(prices: list[float]) -> RiskMetrics:
    """Compute the full risk profile from a single equity/price curve."""
    rets = daily_returns(prices)
    if rets.size < 2:
        return RiskMetrics(note="Not enough history to compute risk metrics.")
    wins = rets[rets > 0].size
    return RiskMetrics(
        sharpe_ratio=_round(sharpe_ratio(rets)),
        annualised_volatility=_round(annualised_volatility(rets)),
        max_drawdown=_round(max_drawdown(prices)),
        var_95=_round(value_at_risk(rets)),
        best_day=_round(float(rets.max() * 100)),
        worst_day=_round(float(rets.min() * 100)),
        win_rate=_round(wins / rets.size * 100),
    )


def correlation_matrix(series: dict[str, list[float]]) -> dict:
    """Return {symbols, matrix} correlation of daily returns across assets."""
    symbols = [s for s, p in series.items() if len(p) > 2]
    if len(symbols) < 2:
        return {"symbols": symbols, "matrix": []}
    rets = [daily_returns(series[s]) for s in symbols]
    n = min(len(r) for r in rets)
    aligned = np.array([r[-n:] for r in rets])
    corr = np.corrcoef(aligned)
    return {"symbols": symbols, "matrix": np.round(corr, 3).tolist()}


def _round(v: float | None, ndigits: int = 2) -> float | None:
    return round(v, ndigits) if v is not None else None
