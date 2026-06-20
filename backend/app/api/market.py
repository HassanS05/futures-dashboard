"""Market-data endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.models.schemas import Quote
from app.services import market

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/quotes", response_model=list[Quote])
async def quotes(symbols: str = Query(..., description="Comma-separated symbols")):
    return await market.get_quotes([s.strip() for s in symbols.split(",") if s.strip()])


@router.get("/search")
async def search(q: str):
    return await market.search_symbols(q)


@router.get("/movers", response_model=list[Quote])
async def movers(kind: str = "gainers"):
    return await market.get_movers(kind)


@router.get("/heatmap")
async def heatmap():
    return await market.get_sector_heatmap()


@router.get("/calendar")
async def calendar():
    return await market.get_economic_calendar()


@router.get("/news")
async def news(tickers: str | None = None):
    tk = [t.strip() for t in tickers.split(",")] if tickers else None
    return await market.get_news(tk)
