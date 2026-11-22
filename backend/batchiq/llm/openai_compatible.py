"""Any OpenAI-compatible chat endpoint: self-hosted open-source models served by
vLLM, Ollama, TGI or a LiteLLM gateway. Keeps the overlay deployable in
environments where no external LLM API is allowed.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from batchiq.llm.base import AssistantResult, LLMProvider, ToolExecutor, ToolSpec

MAX_TURNS = 8


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(self, base_url: str, model: str, api_key: str = "not-needed", timeout: float = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {api_key}"})

    def answer(self, system: str, history: list[dict[str, str]], question: str,
               tools: list[ToolSpec], execute: ToolExecutor) -> AssistantResult:
        api_tools = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                       "parameters": t.parameters}} for t in tools]
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *history,
                                          {"role": "user", "content": question}]
        trace: list[dict[str, Any]] = []
        msg: dict[str, Any] = {}
        for _ in range(MAX_TURNS):
            r = self.http.post(f"{self.base_url}/chat/completions",
                               json={"model": self.model, "messages": messages, "tools": api_tools})
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                break
            for c in calls:
                args = json.loads(c["function"].get("arguments") or "{}")
                try:
                    out = execute(c["function"]["name"], args)
                except Exception as exc:
                    out = json.dumps({"error": str(exc)})
                trace.append({"tool": c["function"]["name"], "input": args})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
        return AssistantResult((msg.get("content") or "").strip(), self.name, self.model, trace)
