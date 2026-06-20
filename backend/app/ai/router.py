"""Multi-model router.

Picks the most relevant provider per task type, with graceful fallback to any
configured provider. The mapping encodes a pragmatic opinion:

  * research / analysis / reports  -> Claude (long-form reasoning)
  * summary / explanation          -> Gemini (fast, cheap) then OpenAI
  * structured / tool-like         -> OpenAI

Override per-request with ``model_override`` ("provider:model" or "provider").
"""

from __future__ import annotations

from app.ai.providers import PROVIDERS, Completion, ProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)

# task -> ordered provider preference
TASK_PREFERENCE: dict[str, list[str]] = {
    "research": ["anthropic", "openai", "gemini"],
    "analysis": ["anthropic", "openai", "gemini"],
    "report": ["anthropic", "openai", "gemini"],
    "summary": ["gemini", "openai", "anthropic"],
    "explanation": ["gemini", "anthropic", "openai"],
    "default": ["anthropic", "openai", "gemini"],
}


def _first_available(order: list[str]):
    for name in order:
        provider = PROVIDERS.get(name)
        if provider and provider.available():
            return provider
    return None


async def route(
    *, task: str, system: str, prompt: str, model_override: str | None = None
) -> Completion:
    """Resolve a provider/model for ``task`` and run the completion."""
    if model_override:
        provider_name, _, model = model_override.partition(":")
        provider = PROVIDERS.get(provider_name)
        if not provider or not provider.available():
            raise ProviderError(f"Requested provider '{provider_name}' is not available.")
        return await provider.complete(system, prompt, model or None)

    order = TASK_PREFERENCE.get(task, TASK_PREFERENCE["default"])
    provider = _first_available(order)
    if not provider:
        raise ProviderError(
            "No AI provider configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY "
            "or GOOGLE_API_KEY in the backend environment."
        )
    logger.info("AI task '%s' routed to %s", task, provider.name)
    return await provider.complete(system, prompt)
