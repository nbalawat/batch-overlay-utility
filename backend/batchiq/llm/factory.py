"""Chooses the LLM provider from configuration."""
from __future__ import annotations

import os

from batchiq.config import settings
from batchiq.llm.base import LLMProvider


def build_provider(offline: LLMProvider) -> LLMProvider:
    choice = settings.llm_provider.lower()
    if choice == "auto":
        choice = "anthropic" if (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")) \
            else "offline"
    if choice == "anthropic":
        from batchiq.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=settings.llm_model, effort=settings.llm_effort)
    if choice in ("openai_compatible", "openai-compatible"):
        from batchiq.llm.openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(settings.openai_base_url, settings.llm_model, settings.openai_api_key)
    return offline
