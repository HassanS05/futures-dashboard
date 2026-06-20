"""Portfolio domain service: valuation, P&L and allocation.

Combines persisted positions with live quotes to produce a real-time summary.
"""

from __future__ import annotations

from datetime import datetime

from app.models.schemas import (
    AssetClass,
    PortfolioSummary,
    Position,
    PositionValuation,
)
from app.services import db
from app.services.market import get_quote_map


async def get_summary() -> PortfolioSummary:
    rows = db.list_positions()
    if not rows:
        return PortfolioSummary(
            total_value=0, total_cost=0, total_pnl=0, total_pnl_percent=0,
            day_pnl=0, day_pnl_percent=0, positions=[], allocation={},
        )

    symbols = sorted({r["symbol"].upper() for r in rows})
    quotes = await get_quote_map(symbols)

    valuations: list[PositionValuation] = []
    total_value = total_cost = day_pnl = 0.0

    for r in rows:
        q = quotes.get(r["symbol"].upper())
        price = q.price if q else r["avg_price"]
        change_pct = q.change_percent if q else 0.0
        qty = r["quantity"]
        market_value = price * qty
        cost_basis = r["avg_price"] * qty
        pnl = market_value - cost_basis
        # previous close approximation for the day move
        prev_value = market_value / (1 + change_pct / 100) if change_pct else market_value
        day_pnl += market_value - prev_value

        valuations.append(
            PositionValuation(
                id=r["id"],
                symbol=r["symbol"],
                asset_class=AssetClass(r["asset_class"]),
                quantity=qty,
                avg_price=r["avg_price"],
                source=r.get("source", "manual"),
                price=price,
                market_value=market_value,
                cost_basis=cost_basis,
                pnl=pnl,
                pnl_percent=(pnl / cost_basis * 100) if cost_basis else 0.0,
            )
        )
        total_value += market_value
        total_cost += cost_basis

    # weights + allocation by asset class
    allocation: dict[str, float] = {}
    for v in valuations:
        v.weight = (v.market_value / total_value * 100) if total_value else 0.0
        allocation[v.asset_class.value] = allocation.get(v.asset_class.value, 0.0) + v.weight

    total_pnl = total_value - total_cost
    prev_total = total_value - day_pnl
    return PortfolioSummary(
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_percent=round((total_pnl / total_cost * 100) if total_cost else 0.0, 2),
        day_pnl=round(day_pnl, 2),
        day_pnl_percent=round((day_pnl / prev_total * 100) if prev_total else 0.0, 2),
        positions=sorted(valuations, key=lambda v: v.market_value, reverse=True),
        allocation={k: round(v, 2) for k, v in allocation.items()},
        updated_at=datetime.utcnow(),
    )


def add_position(pos: Position) -> dict:
    return db.upsert_position(pos.model_dump())


def remove_position(pos_id: str) -> None:
    db.delete_position(pos_id)
