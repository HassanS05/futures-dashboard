"""Real-time WebSocket streaming.

Clients connect and subscribe to a set of symbols; the server pushes fresh
quotes on a fixed interval (backed by the cached FMP layer, so polling upstream
stays cheap). This is the realtime backbone the dashboard subscribes to.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.services import alerts, market, portfolio

logger = get_logger(__name__)
router = APIRouter()

_PUSH_INTERVAL = 5  # seconds


@router.websocket("/ws/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    symbols: list[str] = []
    try:
        # initial subscription frame: {"symbols": ["BTCUSD", "AAPL"]}
        first = await asyncio.wait_for(ws.receive_text(), timeout=10)
        symbols = json.loads(first).get("symbols", [])
    except (asyncio.TimeoutError, json.JSONDecodeError):
        symbols = []

    async def push_loop() -> None:
        while True:
            payload: dict = {"type": "tick"}
            if symbols:
                quotes = await market.get_quotes(symbols)
                payload["quotes"] = [q.model_dump() for q in quotes]
            summary = await portfolio.get_summary()
            payload["portfolio"] = {
                "total_value": summary.total_value,
                "total_pnl": summary.total_pnl,
                "total_pnl_percent": summary.total_pnl_percent,
                "day_pnl": summary.day_pnl,
                "day_pnl_percent": summary.day_pnl_percent,
            }
            triggered = await alerts.evaluate()
            if triggered:
                payload["alerts"] = triggered
            await ws.send_json(payload)
            await asyncio.sleep(_PUSH_INTERVAL)

    async def recv_loop() -> None:
        nonlocal symbols
        while True:
            msg = await ws.receive_text()
            try:
                symbols = json.loads(msg).get("symbols", symbols)
            except json.JSONDecodeError:
                continue

    try:
        await asyncio.gather(push_loop(), recv_loop())
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as exc:  # noqa: BLE001 — keep the socket robust
        logger.warning("WebSocket closed: %s", exc)
