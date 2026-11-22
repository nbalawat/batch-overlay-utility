"""Provider-neutral LLM contract for the operations assistant.

Each provider owns its own tool-calling loop, because the wire formats (and
details like thinking blocks that must be passed back unchanged) differ.
Callers only see `ToolSpec` in and `AssistantResult` out.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

ToolExecutor = Callable[[str, dict[str, Any]], str]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]   # JSON schema for the input object


@dataclass
class AssistantResult:
    answer: str
    provider: str
    model: str
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    note: str | None = None


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def answer(self, system: str, history: list[dict[str, str]], question: str,
               tools: list[ToolSpec], execute: ToolExecutor) -> AssistantResult: ...
