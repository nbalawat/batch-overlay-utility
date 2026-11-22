"""Dependency providers (single place to swap implementations or add auth)."""
from __future__ import annotations

from functools import lru_cache

from batchiq.assistant.agent import Assistant
from batchiq.service import EstateService


@lru_cache(maxsize=1)
def get_service() -> EstateService:
    return EstateService()


_assistant: Assistant | None = None


def get_assistant() -> Assistant:
    global _assistant
    if _assistant is None:
        _assistant = Assistant(get_service())
    return _assistant


def reset_assistant() -> None:
    global _assistant
    _assistant = None
