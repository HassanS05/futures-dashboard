"""Provider adapters with a single uniform interface.

Each provider implements ``complete(system, prompt) -> str``. SDKs are imported
lazily so the backend boots even when a provider isn't installed/configured.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Completion:
    content: str
    provider: str
    model: str


class ProviderError(RuntimeError):
    pass


class AnthropicProvider:
    name = "anthropic"

    def available(self) -> bool:
        return bool(get_settings().anthropic_api_key)

    async def complete(self, system: str, prompt: str, model: str | None = None) -> Completion:
        from anthropic import AsyncAnthropic

        settings = get_settings()
        model = model or settings.anthropic_model
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        return Completion(content=text, provider=self.name, model=model)


class OpenAIProvider:
    name = "openai"

    def available(self) -> bool:
        return bool(get_settings().openai_api_key)

    async def complete(self, system: str, prompt: str, model: str | None = None) -> Completion:
        from openai import AsyncOpenAI

        settings = get_settings()
        model = model or settings.openai_model
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2048,
        )
        return Completion(content=resp.choices[0].message.content or "", provider=self.name, model=model)


class GeminiProvider:
    name = "gemini"

    def available(self) -> bool:
        return bool(get_settings().google_api_key)

    async def complete(self, system: str, prompt: str, model: str | None = None) -> Completion:
        import google.generativeai as genai

        settings = get_settings()
        model = model or settings.gemini_model
        genai.configure(api_key=settings.google_api_key)
        gm = genai.GenerativeModel(model, system_instruction=system)
        resp = await gm.generate_content_async(prompt)
        return Completion(content=resp.text, provider=self.name, model=model)


PROVIDERS = {
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
    "gemini": GeminiProvider(),
}
