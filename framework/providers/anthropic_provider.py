"""Anthropic Claude adapter."""
from __future__ import annotations
from framework.providers.base import LLMProvider, LLMResponse


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str = "claude-sonnet-4-6"):
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for AnthropicProvider. "
                "Install it with: pip install 'devflow-kit[anthropic]' or pip install anthropic"
            ) from exc
        self.client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY
        self.model = model

    async def complete(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        # Convert ToolDef → Anthropic format
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=anthropic_tools,
            messages=messages,
        )
        usage = response.usage
        tool_calls = [
            {"id": b.id, "name": b.name, "input": b.input}
            for b in response.content if b.type == "tool_use"
        ]
        text = next((b.text for b in response.content if b.type == "text"), None)
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=usage.input_tokens + getattr(usage, "cache_creation_input_tokens", 0),
            output_tokens=usage.output_tokens,
            cached_tokens=getattr(usage, "cache_read_input_tokens", 0),
            stop_reason=response.stop_reason,
        )

    def format_tool_result(self, tool_use_id, content):
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}

    def format_assistant_message(self, response: LLMResponse) -> dict:
        content = []
        if response.text:
            content.append({"type": "text", "text": response.text})
        for tc in response.tool_calls:
            content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
        return {"role": "assistant", "content": content}
