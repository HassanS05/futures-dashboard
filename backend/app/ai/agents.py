"""The five specialised investment-copilot agents.

Each agent = a curated system prompt + a task type (drives model routing) +
optional live data enrichment. Agents are read-only advisors: they never place
orders or move funds, and the prompts make that explicit.
"""

from __future__ import annotations

import json

from app.ai.router import route
from app.models.schemas import AIAgent, AIResponse
from app.services import market, portfolio

_DISCLAIMER = (
    "You are part of HR5 Invest, a premium personal investment platform. "
    "You provide educational analysis only — never financial advice, never "
    "guarantees. You never request seed phrases or private keys. Be precise, "
    "structured, and use markdown."
)

_AGENTS: dict[AIAgent, dict] = {
    AIAgent.portfolio: {
        "task": "analysis",
        "system": _DISCLAIMER + (
            " You are the Portfolio AI: analyse diversification, concentration "
            "risk, exposure by asset class, and suggest rebalancing. Always show "
            "concrete numbers and a short action list."
        ),
    },
    AIAgent.dca: {
        "task": "analysis",
        "system": _DISCLAIMER + (
            " You are the DCA AI: optimise dollar-cost-averaging plans, compute "
            "average entry prices, simulate accumulation scenarios and project "
            "outcomes with clear assumptions."
        ),
    },
    AIAgent.research: {
        "task": "research",
        "system": _DISCLAIMER + (
            " You are the Crypto Research AI: assess projects on fundamentals, "
            "tokenomics, TVL, on-chain activity, team, backers, competitors and "
            "risks. End with a 0-100 score and the top 3 risks."
        ),
    },
    AIAgent.market: {
        "task": "summary",
        "system": _DISCLAIMER + (
            " You are the Market AI: produce a crisp daily market briefing — key "
            "moves, drivers, notable events and opportunities to watch."
        ),
    },
    AIAgent.journal: {
        "task": "analysis",
        "system": _DISCLAIMER + (
            " You are the Trading Journal AI: review trading performance, surface "
            "recurring mistakes, discipline issues and statistics, then give "
            "personalised, actionable feedback."
        ),
    },
}


async def _enrich(agent: AIAgent, context: dict | None) -> str:
    """Attach live platform data relevant to the agent as JSON context."""
    parts: list[str] = []
    if agent in (AIAgent.portfolio, AIAgent.dca, AIAgent.journal):
        summary = await portfolio.get_summary()
        parts.append("PORTFOLIO:\n" + summary.model_dump_json(indent=2))
    if agent == AIAgent.market:
        gainers = await market.get_movers("gainers")
        sectors = await market.get_sector_heatmap()
        parts.append("TOP_GAINERS:\n" + json.dumps([g.model_dump() for g in gainers[:5]], default=str))
        parts.append("SECTORS:\n" + json.dumps(sectors))
    if context:
        parts.append("USER_CONTEXT:\n" + json.dumps(context, default=str))
    return "\n\n".join(parts)


async def run_agent(
    agent: AIAgent, prompt: str, context: dict | None = None, model_override: str | None = None
) -> AIResponse:
    spec = _AGENTS[agent]
    enrichment = await _enrich(agent, context)
    full_prompt = f"{prompt}\n\n---\nLIVE DATA:\n{enrichment}" if enrichment else prompt
    completion = await route(
        task=spec["task"],
        system=spec["system"],
        prompt=full_prompt,
        model_override=model_override,
    )
    return AIResponse(
        agent=agent,
        model_used=completion.model,
        provider=completion.provider,
        content=completion.content,
    )
