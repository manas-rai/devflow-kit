"""Provider abstraction — canonical types and LLMProvider interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDef:
    """Canonical tool definition — provider-agnostic."""
    name: str
    description: str
    parameters: dict  # JSON Schema object with properties/required


@dataclass
class CanonicalMessage:
    """Normalized message for the agentic loop."""
    role: str  # "user" | "assistant"
    content: str | list[dict]  # text string or list of content blocks


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""
    text: str | None
    tool_calls: list[dict]  # [{"id": str, "name": str, "input": dict}, ...]
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens"


class LLMProvider(ABC):
    """Abstract interface — all providers implement this."""

    @abstractmethod
    async def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[ToolDef],
        max_tokens: int = 4096,
    ) -> LLMResponse: ...

    @abstractmethod
    def format_tool_result(self, tool_use_id: str, name: str, content: str) -> dict: ...

    @abstractmethod
    def format_assistant_message(self, response: LLMResponse) -> dict: ...
