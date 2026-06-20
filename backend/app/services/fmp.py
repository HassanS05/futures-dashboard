"""Async client for Financial Modeling Prep (FMP).

Single choke-point for all outbound market-data calls so caching, retries and
error handling live in one place. Falls back gracefully (returns empty) when no
API key is configured, so the app still boots for UI development.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import get_settings
from app.core.cache import cache
from app.core.logging import get_logger

logger = get_logger(__name__)

_BASE = "https://financialmodelingprep.com/api/v3"
_STABLE = "https://financialmodelingprep.com/stable"


class FMPClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(self, url: str, params: dict[str, Any] | None = None) -> Any:
        settings = get_settings()
        if not settings.fmp_api_key:
            logger.warning("FMP_API_KEY missing — returning empty market data.")
            return []
        params = {**(params or {}), "apikey": settings.fmp_api_key}
        cache_key = f"fmp:{url}:{sorted((params or {}).items())}"

        async def _fetch() -> Any:
            client = await self._get_client()
            for attempt in range(3):
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    return resp.json()
                except httpx.HTTPStatusError as exc:
                    # 4xx (bad/missing key, unknown symbol) won't recover — fail fast.
                    if 400 <= exc.response.status_code < 500:
                        logger.warning(
                            "FMP %s for %s — not retrying (check FMP_API_KEY).",
                            exc.response.status_code,
                            url,
                        )
                        return []
                    wait = 2**attempt
                    logger.warning("FMP %s; retry in %ss", exc, wait)
                    await asyncio.sleep(wait)
                except (httpx.TransportError, httpx.TimeoutException) as exc:
                    wait = 2**attempt
                    logger.warning("FMP network error (%s); retry in %ss", exc, wait)
                    await asyncio.sleep(wait)
            logger.error("FMP request gave up after retries: %s", url)
            return []

        return await cache.get_or_set(cache_key, _fetch, ttl=settings.cache_ttl_seconds)

    # --- public helpers -------------------------------------------------
    async def quote(self, symbols: list[str]) -> list[dict]:
        if not symbols:
            return []
        joined = ",".join(symbols)
        return await self._request(f"{_BASE}/quote/{joined}") or []

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        return await self._request(
            f"{_BASE}/search", {"query": query, "limit": limit}
        ) or []

    async def historical(self, symbol: str, days: int = 365) -> list[dict]:
        data = await self._request(
            f"{_BASE}/historical-price-full/{symbol}",
            {"timeseries": days},
        )
        if isinstance(data, dict):
            return data.get("historical", [])
        return data or []

    async def crypto_list(self) -> list[dict]:
        return await self._request(f"{_BASE}/symbol/available-cryptocurrencies") or []

    async def market_movers(self, kind: str = "gainers") -> list[dict]:
        # kind: gainers | losers | actives
        return await self._request(f"{_BASE}/stock_market/{kind}") or []

    async def sector_performance(self) -> list[dict]:
        return await self._request(f"{_BASE}/sectors-performance") or []

    async def economic_calendar(self) -> list[dict]:
        return await self._request(f"{_BASE}/economic_calendar") or []

    async def news(self, tickers: list[str] | None = None, limit: int = 20) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if tickers:
            params["tickers"] = ",".join(tickers)
        return await self._request(f"{_BASE}/stock_news", params) or []


fmp = FMPClient()
