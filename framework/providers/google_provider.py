"""Google Gemini adapter."""

from __future__ import annotations

import os

from google import genai
from google.genai import types

from framework.providers.base import LLMProvider, LLMResponse, ToolDef


class GoogleProvider(LLMProvider):
    """Google Gemini provider."""

    def __init__(self, model: str = "gemini-2.5-flash"):
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is missing")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model

    async def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        gemini_tools = [self._tool_to_gemini(t) for t in tools] if tools else None

        # Build contents array
        contents = []
        for msg in messages:
            if msg["role"] == "user":
                parts = []
                if "content" in msg and isinstance(msg["content"], list):
                    for part in msg["content"]:
                        if part.get("type") == "tool_result":
                            parts.append(
                                types.Part(
                                    function_response=types.FunctionResponse(
                                        id=part.get("tool_use_id", ""),
                                        name=part.get("name", "unknown_tool"),
                                        response={"result": part["content"]},
                                    )
                                )
                            )
                        else:
                            parts.append(types.Part.from_text(text=part.get("text", "")))
                else:
                    parts.append(types.Part.from_text(text=msg["content"]))
                contents.append(types.Content(role="user", parts=parts))
            elif msg["role"] in ("model", "assistant"):
                contents.append(types.Content(role="model", parts=msg["content"]))

        config = types.GenerateContentConfig(
            system_instruction=system, tools=gemini_tools, temperature=0.0
        )

        # Call Gemini
        response = self.client.models.generate_content(
            model=self.model_name, contents=contents, config=config
        )

        text = None
        tool_calls = []
        stop_reason = "end_turn"

        if response.candidates:
            candidate = response.candidates[0]
            if candidate.finish_reason == "STOP":
                stop_reason = "end_turn"
            for part in candidate.content.parts:
                if part.text:
                    text = part.text
                elif part.function_call:
                    tool_calls.append(
                        {
                            "id": getattr(part.function_call, "id", part.function_call.name),
                            "name": part.function_call.name,
                            "input": dict(part.function_call.args),
                            "thought_signature": getattr(part, "thought_signature", None),
                            "thought": getattr(part, "thought", None),
                        }
                    )
                    stop_reason = "tool_use"

        in_tok = response.usage_metadata.prompt_token_count if response.usage_metadata else 0
        out_tok = response.usage_metadata.candidates_token_count if response.usage_metadata else 0

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cached_tokens=0,
            stop_reason=stop_reason,
        )

    def format_tool_result(self, tool_use_id: str, name: str, content: str) -> dict:
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "name": name,
            "content": content,
        }

    def format_assistant_message(self, response: LLMResponse) -> dict:
        parts = []
        if response.text:
            parts.append(types.Part.from_text(text=response.text))
        for tc in response.tool_calls:
            part = types.Part(
                function_call=types.FunctionCall(id=tc.get("id"), name=tc["name"], args=tc["input"])
            )
            if tc.get("thought_signature"):
                part.thought_signature = tc.get("thought_signature")
            if tc.get("thought"):
                part.thought = tc.get("thought")
            parts.append(part)
        return {"role": "model", "content": parts}

    def _tool_to_gemini(self, tool: ToolDef) -> types.Tool:
        props = {}
        for k, v in tool.parameters.get("properties", {}).items():
            type_map = {
                "integer": "INTEGER",
                "number": "NUMBER",
                "boolean": "BOOLEAN",
                "array": "ARRAY",
                "object": "OBJECT",
            }
            t_type = type_map.get(v["type"], "STRING")
            props[k] = {"type": t_type, "description": v.get("description", "")}

        return types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters={
                        "type": "OBJECT",
                        "properties": props,
                        "required": tool.parameters.get("required", []),
                    },
                )
            ]
        )
