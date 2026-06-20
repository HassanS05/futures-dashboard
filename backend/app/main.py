"""HR5 Invest API entrypoint.

Run locally:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ai, analytics, futures, market, portfolio, ws
from app.config import get_settings
from app.core.logging import get_logger
from app.services.db import init_db
from app.services.fmp import fmp

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("HR5 Invest API ready.")
    yield
    await fmp.close()


app = FastAPI(
    title="HR5 Invest API",
    version="0.1.0",
    description="Premium personal investment platform — market data, portfolio, analytics & AI copilot.",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (market, portfolio, analytics, ai, futures):
    app.include_router(module.router)
app.include_router(ws.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "hr5-invest", "version": "0.1.0"}
