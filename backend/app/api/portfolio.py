"""Portfolio endpoints — positions, transactions, summary."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.security import SeedPhraseRejected, reject_seed_phrase
from app.models.schemas import PortfolioSummary, Position, Transaction
from app.services import db, history, portfolio

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=PortfolioSummary)
async def summary():
    return await portfolio.get_summary()


@router.get("/performance")
async def performance():
    """Real day/week/month/year/YTD returns from daily snapshots."""
    await portfolio.get_summary()  # ensure today's snapshot is recorded
    return history.performance()


@router.get("/equity-curve")
async def equity_curve():
    return history.equity_curve()


@router.get("/positions")
async def positions():
    return db.list_positions()


@router.post("/positions", response_model=Position)
async def add_position(pos: Position):
    try:
        reject_seed_phrase(pos.symbol)
    except SeedPhraseRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return portfolio.add_position(pos)


@router.delete("/positions/{pos_id}")
async def delete_position(pos_id: str):
    portfolio.remove_position(pos_id)
    return {"deleted": pos_id}


@router.get("/transactions", response_model=list[Transaction])
async def transactions(limit: int = 50):
    return db.list_transactions(limit)


@router.post("/transactions", response_model=Transaction)
async def add_transaction(tx: Transaction):
    return db.add_transaction(tx.model_dump(mode="json"))
