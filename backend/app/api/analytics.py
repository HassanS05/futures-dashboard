"""Analytics endpoints — risk metrics & correlations from live history."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.models.schemas import RiskMetrics
from app.services import db
from app.services.analytics import compute_risk, correlation_matrix
from app.services.fmp import fmp

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _closes(historical: list[dict]) -> list[float]:
    # FMP returns newest-first; reverse to chronological.
    return [h["close"] for h in reversed(historical) if h.get("close") is not None]


@router.get("/risk/{symbol}", response_model=RiskMetrics)
async def risk(symbol: str, days: int = Query(365, ge=30, le=1825)):
    history = await fmp.historical(symbol, days)
    return compute_risk(_closes(history))


@router.get("/correlations")
async def correlations(days: int = Query(180, ge=30, le=730)):
    """Correlation matrix across the symbols currently held."""
    symbols = sorted({p["symbol"] for p in db.list_positions()})
    series: dict[str, list[float]] = {}
    for sym in symbols:
        series[sym] = _closes(await fmp.historical(sym, days))
    return correlation_matrix(series)
