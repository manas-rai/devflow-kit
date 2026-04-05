"""Google Gemini adapter — stub implementation."""
from __future__ import annotations
from framework.providers.base import LLMProvider, LLMResponse, ToolDef


class GoogleProvider(LLMProvider):
    """Stub Google Gemini provider.

    Not yet implemented. Install ``google-generativeai`` and implement
    this class to enable Gemini support.
    """

    def __init__(self, model: str = "gemini-1.5-pro"):
        self.model = model

    async def complete(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        raise NotImplementedError(
            "GoogleProvider is not yet implemented. "
            "To use Google Gemini, install 'google-generativeai>=0.8' and implement "
            "framework/providers/google_provider.py. "
            "For now, use provider='anthropic' or provider='openai'."
        )

    def format_tool_result(self, tool_use_id: str, content: str) -> dict:
        raise NotImplementedError(
            "GoogleProvider is not yet implemented. "
            "Use provider='anthropic' or provider='openai' instead."
        )

    def format_assistant_message(self, response: LLMResponse) -> dict:
        raise NotImplementedError(
            "GoogleProvider is not yet implemented. "
            "Use provider='anthropic' or provider='openai' instead."
        )
