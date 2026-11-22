"""Claude via the official Anthropic SDK (default provider).

Works against the Claude API directly. For Bedrock, Vertex AI or Foundry, swap
the client for the SDK's platform client (AnthropicBedrockMantle,
AnthropicVertex, AnthropicFoundry); the loop below is unchanged.
"""
from __future__ import annotations

import json
from typing import Any

import anthropic

from batchiq.llm.base import AssistantResult, LLMProvider, ToolExecutor, ToolSpec

MAX_TURNS = 8


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium",
                 client: anthropic.Anthropic | None = None) -> None:
        self.model = model
        self.effort = effort
        self.client = client or anthropic.Anthropic()

    def answer(self, system: str, history: list[dict[str, str]], question: str,
               tools: list[ToolSpec], execute: ToolExecutor) -> AssistantResult:
        api_tools = [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                     for t in tools]
        messages: list[dict[str, Any]] = [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": question})
        trace: list[dict[str, Any]] = []
        response = None
        for _ in range(MAX_TURNS):
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                tools=api_tools,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                # Server-side refusal fallback: routes a declined request to a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            if response.stop_reason == "refusal":
                return AssistantResult("I can't help with that request.", self.name, response.model, trace)
            # Pass every block back unchanged (thinking blocks must be preserved).
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                break
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    out = execute(block.name, dict(block.input))
                    is_error = False
                except Exception as exc:  # report tool errors back to the model
                    out, is_error = json.dumps({"error": str(exc)}), True
                trace.append({"tool": block.name, "input": dict(block.input)})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out,
                                "is_error": is_error})
            messages.append({"role": "user", "content": results})
        text = "".join(b.text for b in (response.content if response else []) if b.type == "text")
        return AssistantResult(text.strip() or "(no answer)", self.name, response.model if response else self.model,
                               trace)
