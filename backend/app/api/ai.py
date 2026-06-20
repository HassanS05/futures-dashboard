"""AI copilot endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.ai.agents import run_agent
from app.ai.providers import PROVIDERS, ProviderError
from app.config import get_settings
from app.models.schemas import AIRequest, AIResponse

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
async def status():
    settings = get_settings()
    return {
        "enabled": settings.has_any_ai,
        "providers": {name: p.available() for name, p in PROVIDERS.items()},
        "default_model": settings.anthropic_model,
    }


@router.post("/ask", response_model=AIResponse)
async def ask(req: AIRequest):
    try:
        return await run_agent(req.agent, req.prompt, req.context, req.model_override)
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
