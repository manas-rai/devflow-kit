"""OpenAI adapter."""

from __future__ import annotations

import json

from framework.providers.base import LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str = "gpt-4o"):
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for OpenAIProvider. "
                "Install it with: pip install 'devflow-kit[openai]' or pip install openai"
            ) from exc
        self.client = openai.OpenAI()
        self.model = model

    async def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        oai_messages = [{"role": "system", "content": system}] + messages
        oai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=oai_messages,
            tools=oai_tools or None,
        )
        choice = response.choices[0]
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": json.loads(tc.function.arguments),
                    }
                )
        return LLMResponse(
            text=choice.message.content,
            tool_calls=tool_calls,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            cached_tokens=getattr(response.usage, "cached_tokens", 0),
            stop_reason="tool_use" if tool_calls else "end_turn",
        )

    def format_tool_result(self, tool_use_id: str, name: str, content: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_use_id, "name": name, "content": content}

    def format_assistant_message(self, response: LLMResponse) -> dict:
        tool_calls = None
        if response.tool_calls:
            tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["input"]),
                    },
                }
                for tc in response.tool_calls
            ]
        return {"role": "assistant", "content": response.text or "", "tool_calls": tool_calls}
