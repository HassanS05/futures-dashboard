"""Market-data domain service: normalises FMP payloads into our schemas."""

from __future__ import annotations

from app.models.schemas import AssetClass, Quote
from app.services.fmp import fmp

# Heuristic asset-class detection from a symbol.
_CRYPTO_SUFFIX = "USD"


def _classify(symbol: str) -> AssetClass:
    s = symbol.upper()
    if s.endswith(_CRYPTO_SUFFIX) and len(s) > 5 and "." not in s:
        return AssetClass.crypto
    return AssetClass.stock


def _to_quote(raw: dict) -> Quote:
    symbol = raw.get("symbol", "")
    return Quote(
        symbol=symbol,
        name=raw.get("name"),
        price=raw.get("price") or 0.0,
        change=raw.get("change") or 0.0,
        change_percent=raw.get("changesPercentage") or 0.0,
        day_high=raw.get("dayHigh"),
        day_low=raw.get("dayLow"),
        market_cap=raw.get("marketCap"),
        volume=raw.get("volume"),
        asset_class=_classify(symbol),
    )


async def get_quotes(symbols: list[str]) -> list[Quote]:
    raw = await fmp.quote(symbols)
    return [_to_quote(r) for r in raw]


async def get_quote_map(symbols: list[str]) -> dict[str, Quote]:
    return {q.symbol.upper(): q for q in await get_quotes(symbols)}


async def search_symbols(query: str) -> list[dict]:
    return await fmp.search(query)


async def get_movers(kind: str = "gainers") -> list[Quote]:
    raw = await fmp.market_movers(kind)
    return [_to_quote(r) for r in raw]


async def get_sector_heatmap() -> list[dict]:
    """Returns [{sector, changePercent}] for the market heatmap."""
    raw = await fmp.sector_performance()
    out = []
    for r in raw:
        pct = r.get("changesPercentage") or r.get("changePercent") or "0"
        if isinstance(pct, str):
            pct = pct.replace("%", "").strip() or "0"
        out.append({"sector": r.get("sector", ""), "change": float(pct)})
    return out


async def get_economic_calendar() -> list[dict]:
    return await fmp.economic_calendar()


async def get_news(tickers: list[str] | None = None) -> list[dict]:
    return await fmp.news(tickers)
