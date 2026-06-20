"""Futures calculator endpoint (preserves the original prototype feature)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import FuturesResult, FuturesScenario
from app.services.futures import CONTRACTS, compute

router = APIRouter(prefix="/api/futures", tags=["futures"])


@router.get("/contracts")
async def contracts():
    return CONTRACTS


@router.post("/calc", response_model=FuturesResult)
async def calc(scenario: FuturesScenario):
    try:
        return compute(scenario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
