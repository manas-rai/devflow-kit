# Multi-Provider LLM Architecture

> **Purpose**: Design a provider-agnostic LLM layer that works with Anthropic, OpenAI,
> Google Gemini, Mistral, or any future provider without changing agent code.

---

## The Problem: Every Provider is Different

All three major providers expose the same concept (tool-calling LLMs) but with
incompatible API formats:

### Tool Schema Format

**Anthropic:**
```json
{
  "name": "read_jira_ticket",
  "description": "Read a Jira ticket",
  "input_schema": {
    "type": "object",
    "properties": {
      "issue_key": { "type": "string" }
    },
    "required": ["issue_key"]
  }
}
```

**OpenAI:**
```json
{
  "type": "function",
  "function": {
    "name": "read_jira_ticket",
    "description": "Read a Jira ticket",
    "parameters": {
      "type": "object",
      "properties": {
        "issue_key": { "type": "string" }
      },
      "required": ["issue_key"]
    }
  }
}
```

**Google Gemini:**
```json
{
  "function_declarations": [{
    "name": "read_jira_ticket",
    "description": "Read a Jira ticket",
    "parameters": {
      "type": "OBJECT",
      "properties": {
        "issue_key": { "type": "STRING" }
      },
      "required": ["issue_key"]
    }
  }]
}
```

### Message / Response Format

**Anthropic response:**
```json
{
  "content": [
    { "type": "text", "text": "I'll read the ticket" },
    { "type": "tool_use", "id": "tu_abc", "name": "read_jira_ticket", "input": {"issue_key": "CWH-38"} }
  ],
  "stop_reason": "tool_use"
}
```

**OpenAI response:**
```json
{
  "choices": [{
    "message": {
      "content": "I'll read the ticket",
      "tool_calls": [{
        "id": "call_abc",
        "type": "function",
        "function": { "name": "read_jira_ticket", "arguments": "{\"issue_key\": \"CWH-38\"}" }
      }]
    },
    "finish_reason": "tool_calls"
  }]
}
```

**Google Gemini response:**
```json
{
  "candidates": [{
    "content": {
      "parts": [
        { "text": "I'll read the ticket" },
        { "functionCall": { "name": "read_jira_ticket", "args": {"issue_key": "CWH-38"} } }
      ]
    },
    "finishReason": "STOP"
  }]
}
```

### Tool Result Format

**Anthropic:**
```json
{ "type": "tool_result", "tool_use_id": "tu_abc", "content": "Ticket text..." }
```

**OpenAI:**
```json
{ "role": "tool", "tool_call_id": "call_abc", "content": "Ticket text..." }
```

**Google Gemini:**
```json
{ "role": "user", "parts": [{ "functionResponse": { "name": "read_jira_ticket", "response": { "result": "Ticket text..." } } }] }
```

---

## Solution: Canonical Internal Format + Per-Provider Adapters

Define one **canonical format** internally and convert at the boundary.
Agent code only ever uses the canonical format. Adapters translate.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Code                                │
│  agent.py / sdk_runner.py                                        │
│                                                                  │
│  Uses CANONICAL format only:                                     │
│    ToolDef, CanonicalMessage, ProviderResponse                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Provider Abstraction                          │
│  framework/providers/                                            │
│                                                                  │
│  ┌────────────┐  ┌──────────────┐  ┌────────────┐  ┌─────────┐ │
│  │ Anthropic  │  │   OpenAI     │  │   Google   │  │ Mistral │ │
│  │ Adapter    │  │   Adapter    │  │   Adapter  │  │ Adapter │ │
│  └────────────┘  └──────────────┘  └────────────┘  └─────────┘ │
│       │                │                 │               │       │
│       ▼                ▼                 ▼               ▼       │
│  Converts canonical format to/from each provider's API format    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Provider APIs                                  │
│                                                                  │
│  api.anthropic.com   api.openai.com   generativelanguage.google  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Canonical Data Models

```python
# framework/providers/models.py
"""Canonical data models. All provider adapters convert to/from these."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal


# --- Tool Definition (canonical) ---

@dataclass
class ToolParam:
    """A single parameter for a tool."""
    name: str
    type: Literal["string", "number", "boolean", "array", "object"]
    description: str
    required: bool = True
    enum: list[str] | None = None  # For restricted string values


@dataclass
class ToolDef:
    """Canonical tool definition. Provider adapters convert this to their format."""
    name: str
    description: str
    params: list[ToolParam]

    def to_json_schema(self) -> dict:
        """Convert to JSON Schema (shared base for all providers)."""
        properties = {}
        required = []
        for p in self.params:
            prop: dict[str, Any] = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }


# --- Message (canonical) ---

@dataclass
class ToolCall:
    """A single tool call from the LLM."""
    id: str        # Provider-assigned ID (used to match results)
    name: str      # Tool name
    input: dict    # Tool arguments


@dataclass
class CanonicalMessage:
    """A normalized message for any provider."""
    role: Literal["user", "assistant"]
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class ToolResult:
    """Result of a tool execution, to be sent back to the LLM."""
    tool_call_id: str   # Matches ToolCall.id
    tool_name: str      # Matches ToolCall.name
    content: str        # The tool output (string)
    is_error: bool = False


# --- Provider Response (canonical) ---

@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""
    text: str | None                          # Final text if any
    tool_calls: list[ToolCall]                # Tools to execute
    input_tokens: int                         # Tokens in this request
    output_tokens: int                        # Tokens generated
    cached_tokens: int = 0                    # Tokens served from cache
    stop_reason: str = "end_turn"             # "end_turn" | "tool_use" | "max_tokens"
```

---

## Provider Abstraction Layer

```python
# framework/providers/base.py
"""Abstract base class that all provider adapters must implement."""

from __future__ import annotations
from abc import ABC, abstractmethod
from framework.providers.models import ToolDef, CanonicalMessage, LLMResponse, ToolResult


class LLMProvider(ABC):
    """Abstract interface for LLM providers.

    Each provider adapter:
    1. Converts ToolDef → provider-specific tool schema
    2. Converts CanonicalMessage → provider-specific message format
    3. Calls the provider's HTTP API
    4. Converts provider response → LLMResponse (canonical)
    """

    @abstractmethod
    async def complete(
        self,
        system: str,
        messages: list[CanonicalMessage],
        tools: list[ToolDef],
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a request and return a canonical response."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""
        ...

    @property
    def supports_caching(self) -> bool:
        """Whether this provider supports prompt caching."""
        return False
```

---

## All Four Provider Adapters

```python
# framework/providers/anthropic_provider.py
import anthropic
from framework.providers.base import LLMProvider
from framework.providers.models import (
    ToolDef, CanonicalMessage, LLMResponse, ToolCall, ToolResult
)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    name = "Anthropic Claude"
    supports_caching = True

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY
        self.model = model

    async def complete(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        # Convert canonical → Anthropic format
        anthropic_tools = [self._tool_to_anthropic(t) for t in tools]
        anthropic_messages = [self._msg_to_anthropic(m) for m in messages]

        # System prompt with cache control for multi-turn efficiency
        system_blocks = [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }]

        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_blocks,
            tools=anthropic_tools,
            messages=anthropic_messages,
        )

        # Convert Anthropic response → canonical
        usage = response.usage
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=b.input)
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

    def _tool_to_anthropic(self, tool: ToolDef) -> dict:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.to_json_schema(),
        }

    def _msg_to_anthropic(self, msg: CanonicalMessage) -> dict:
        if msg.tool_results:
            # Tool results go as user message with tool_result blocks
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.tool_call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in msg.tool_results
                ],
            }
        if msg.tool_calls:
            # Assistant message with tool_use blocks
            content = []
            if msg.text:
                content.append({"type": "text", "text": msg.text})
            for tc in msg.tool_calls:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            return {"role": msg.role, "content": content}
        # Plain text message
        return {"role": msg.role, "content": msg.text or ""}
```

```python
# framework/providers/openai_provider.py
import json
import openai
from framework.providers.base import LLMProvider
from framework.providers.models import (
    ToolDef, CanonicalMessage, LLMResponse, ToolCall
)


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider."""

    name = "OpenAI GPT"

    def __init__(self, model: str = "gpt-4o"):
        self.client = openai.OpenAI()  # OPENAI_API_KEY
        self.model = model

    async def complete(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        # Convert canonical → OpenAI format
        oai_tools = [self._tool_to_openai(t) for t in tools]
        oai_messages = [{"role": "system", "content": system}] + [
            self._msg_to_openai(m) for m in messages
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=oai_messages,
            tools=oai_tools if oai_tools else None,
        )

        # Convert OpenAI response → canonical
        choice = response.choices[0]
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=json.loads(tc.function.arguments),
                ))

        stop = "tool_use" if tool_calls else "end_turn"
        if choice.finish_reason == "length":
            stop = "max_tokens"

        return LLMResponse(
            text=choice.message.content,
            tool_calls=tool_calls,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            cached_tokens=getattr(response.usage, "prompt_tokens_details", {}).get("cached_tokens", 0),
            stop_reason=stop,
        )

    def _tool_to_openai(self, tool: ToolDef) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.to_json_schema(),
            },
        }

    def _msg_to_openai(self, msg: CanonicalMessage) -> dict | list:
        if msg.tool_results:
            # OpenAI needs one message per tool result
            return [
                {
                    "role": "tool",
                    "tool_call_id": r.tool_call_id,
                    "content": r.content,
                }
                for r in msg.tool_results
            ]
        if msg.tool_calls:
            return {
                "role": "assistant",
                "content": msg.text,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.input),
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
        return {"role": msg.role, "content": msg.text or ""}
```

```python
# framework/providers/google_provider.py
import google.generativeai as genai
from google.generativeai import protos
from framework.providers.base import LLMProvider
from framework.providers.models import (
    ToolDef, CanonicalMessage, LLMResponse, ToolCall
)


class GoogleProvider(LLMProvider):
    """Google Gemini provider."""

    name = "Google Gemini"

    def __init__(self, model: str = "gemini-2.0-flash"):
        genai.configure()  # GOOGLE_API_KEY
        self.model_name = model

    async def complete(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        # Build Gemini tools
        gemini_tools = self._tools_to_gemini(tools)
        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system,
            tools=gemini_tools,
        )

        # Convert messages to Gemini format
        chat = model.start_chat(history=self._msgs_to_gemini_history(messages[:-1]))
        last_msg = messages[-1].text or ""
        response = chat.send_message(last_msg)

        # Convert Gemini response → canonical
        tool_calls = []
        text = None
        for part in response.parts:
            if hasattr(part, "function_call") and part.function_call.name:
                fc = part.function_call
                tool_calls.append(ToolCall(
                    id=fc.name,  # Gemini doesn't have IDs; use name as ID
                    name=fc.name,
                    input=dict(fc.args),
                ))
            elif hasattr(part, "text") and part.text:
                text = part.text

        usage = response.usage_metadata
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=usage.prompt_token_count,
            output_tokens=usage.candidates_token_count,
            stop_reason="tool_use" if tool_calls else "end_turn",
        )

    def _tools_to_gemini(self, tools: list[ToolDef]):
        declarations = []
        for t in tools:
            schema = t.to_json_schema()
            props = {
                k: protos.Schema(
                    type=self._type_map(v["type"]),
                    description=v.get("description", ""),
                )
                for k, v in schema["properties"].items()
            }
            declarations.append(protos.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties=props,
                    required=schema.get("required", []),
                ),
            ))
        return [protos.Tool(function_declarations=declarations)]

    def _type_map(self, json_type: str) -> protos.Type:
        return {
            "string": protos.Type.STRING,
            "number": protos.Type.NUMBER,
            "boolean": protos.Type.BOOLEAN,
            "array": protos.Type.ARRAY,
            "object": protos.Type.OBJECT,
        }.get(json_type, protos.Type.STRING)

    def _msgs_to_gemini_history(self, messages: list[CanonicalMessage]) -> list:
        history = []
        for msg in messages:
            if msg.role == "user":
                history.append({"role": "user", "parts": [msg.text or ""]})
            else:
                history.append({"role": "model", "parts": [msg.text or ""]})
        return history
```

```python
# framework/providers/litellm_provider.py
"""
LiteLLM Provider — alternative to writing individual adapters.

LiteLLM (pip install litellm) is a library that already normalizes
100+ LLM providers into a single OpenAI-compatible interface.

Use this if you want to support many providers without writing individual
adapters for each. The trade-off: you depend on a third-party library.

Supported via LiteLLM:
  - anthropic/claude-sonnet-4-20250514
  - openai/gpt-4o
  - gemini/gemini-2.0-flash
  - mistral/mistral-large-latest
  - cohere/command-r-plus
  - groq/llama-3.1-70b-versatile
  - bedrock/claude-3-5-sonnet  (AWS)
  - azure/gpt-4o               (Azure OpenAI)
  ... and 100+ more

Usage:
    provider = LiteLLMProvider(model="anthropic/claude-sonnet-4-20250514")
    provider = LiteLLMProvider(model="openai/gpt-4o")
    provider = LiteLLMProvider(model="gemini/gemini-2.0-flash")
"""

import json
import litellm
from framework.providers.base import LLMProvider
from framework.providers.models import (
    ToolDef, CanonicalMessage, LLMResponse, ToolCall
)


class LiteLLMProvider(LLMProvider):
    """Universal provider using LiteLLM for format normalization."""

    def __init__(self, model: str = "anthropic/claude-sonnet-4-20250514"):
        self.model = model  # Format: "provider/model-name"

    @property
    def name(self) -> str:
        return f"LiteLLM ({self.model})"

    async def complete(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        # LiteLLM uses OpenAI format natively
        oai_tools = [self._tool_to_openai(t) for t in tools]
        oai_messages = [{"role": "system", "content": system}] + [
            self._msg_to_openai(m) for m in messages
        ]

        response = litellm.completion(
            model=self.model,
            messages=oai_messages,
            tools=oai_tools if oai_tools else None,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=json.loads(tc.function.arguments),
                ))

        return LLMResponse(
            text=choice.message.content,
            tool_calls=tool_calls,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            stop_reason="tool_use" if tool_calls else "end_turn",
        )

    def _tool_to_openai(self, tool: ToolDef) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.to_json_schema(),
            },
        }

    def _msg_to_openai(self, msg: CanonicalMessage) -> dict:
        if msg.tool_results:
            return {
                "role": "tool",
                "tool_call_id": msg.tool_results[0].tool_call_id,
                "content": msg.tool_results[0].content,
            }
        if msg.tool_calls:
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.input)},
                    }
                    for tc in msg.tool_calls
                ],
            }
        return {"role": msg.role, "content": msg.text or ""}
```

---

## Provider Factory

```python
# framework/providers/__init__.py

from __future__ import annotations
from framework.providers.base import LLMProvider


def get_provider(config: str) -> LLMProvider:
    """
    Parse a provider config string and return the correct adapter.

    Format: "provider" or "provider/model"

    Examples:
        "anthropic"                          → AnthropicProvider (default model)
        "anthropic/claude-opus-4-20250514"   → AnthropicProvider (specific model)
        "openai"                             → OpenAIProvider (default model)
        "openai/gpt-4o-mini"                 → OpenAIProvider (cheaper model)
        "google"                             → GoogleProvider (default model)
        "google/gemini-2.0-flash"            → GoogleProvider (specific model)
        "litellm/mistral/mistral-large"      → LiteLLMProvider (any LiteLLM model)
        "cli"                                → None (use Claude CLI runner instead)
    """
    if config == "cli":
        return None  # Signal to use AgentRunner instead of SDKRunner

    parts = config.split("/", 1)
    provider_name = parts[0]
    model = parts[1] if len(parts) > 1 else None

    if provider_name == "anthropic":
        from framework.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model or "claude-sonnet-4-20250514")

    elif provider_name == "openai":
        from framework.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model or "gpt-4o")

    elif provider_name == "google":
        from framework.providers.google_provider import GoogleProvider
        return GoogleProvider(model=model or "gemini-2.0-flash")

    elif provider_name == "litellm":
        # model string for LiteLLM includes the subprovider: "mistral/mistral-large"
        from framework.providers.litellm_provider import LiteLLMProvider
        return LiteLLMProvider(model=model or "anthropic/claude-sonnet-4-20250514")

    else:
        raise ValueError(
            f"Unknown provider: '{provider_name}'. "
            f"Options: anthropic, openai, google, litellm, cli"
        )
```

---

## Tool Registry (Canonical Tool Definitions)

Tools are defined ONCE using `ToolDef`. Each provider adapter converts them to its own format. No duplication.

```python
# framework/tools/registry.py

from framework.providers.models import ToolDef, ToolParam

# ---- Jira Tools ----

JIRA_READ = ToolDef(
    name="read_jira_ticket",
    description="Read a Jira ticket's summary, description, acceptance criteria, and comments.",
    params=[
        ToolParam("issue_key", "string", "Jira issue key e.g. CWH-38"),
    ]
)

JIRA_UPDATE_DESC = ToolDef(
    name="update_jira_description",
    description="Replace the Jira ticket description with refined content.",
    params=[
        ToolParam("issue_key", "string", "Jira issue key"),
        ToolParam("description", "string", "Complete description in markdown"),
    ]
)

JIRA_STORY_POINTS = ToolDef(
    name="update_jira_story_points",
    description="Set story point estimate on a Jira ticket.",
    params=[
        ToolParam("issue_key", "string", "Jira issue key"),
        ToolParam("story_points", "number", "Estimate: 1, 2, 3, 5, or 8"),
    ]
)

JIRA_COMMENT = ToolDef(
    name="post_jira_comment",
    description="Post a comment to a Jira ticket.",
    params=[
        ToolParam("issue_key", "string", "Jira issue key"),
        ToolParam("comment", "string", "Comment text"),
    ]
)

JIRA_TRANSITION = ToolDef(
    name="transition_jira_ticket",
    description="Move a Jira ticket to a new status.",
    params=[
        ToolParam("issue_key", "string", "Jira issue key"),
        ToolParam(
            "status", "string", "Target status",
            enum=["To Do", "In Progress", "In Review", "Done"]
        ),
    ]
)

# ---- GitHub Tools ----

GITHUB_SEARCH = ToolDef(
    name="search_code",
    description="Search for code patterns in the target GitHub repository.",
    params=[
        ToolParam("repo", "string", "GitHub repo in owner/name format"),
        ToolParam("query", "string", "Search query"),
    ]
)

GITHUB_CREATE_ISSUE = ToolDef(
    name="create_github_issue",
    description="Create a GitHub issue with a technical spec.",
    params=[
        ToolParam("repo", "string", "GitHub repo in owner/name format"),
        ToolParam("title", "string", "Issue title"),
        ToolParam("body", "string", "Issue body in markdown"),
    ]
)

# ---- Coding Tools (implementation agent only) ----

CODE_READ = ToolDef(
    name="read_file",
    description="Read a file from the cloned repository.",
    params=[ToolParam("path", "string", "Relative file path from repo root")]
)

CODE_WRITE = ToolDef(
    name="write_file",
    description="Write or overwrite a file in the cloned repository.",
    params=[
        ToolParam("path", "string", "Relative file path"),
        ToolParam("content", "string", "Complete file content"),
    ]
)

CODE_BASH = ToolDef(
    name="run_bash",
    description="Run a bash command in the cloned repository directory.",
    params=[
        ToolParam("command", "string", "Bash command to execute"),
        ToolParam("timeout", "number", "Max seconds to wait (default: 60)", required=False),
    ]
)

CODE_LIST = ToolDef(
    name="list_files",
    description="List files in a directory of the cloned repository.",
    params=[ToolParam("directory", "string", "Directory path (default: .)", required=False)]
)

CODE_GREP = ToolDef(
    name="search_in_repo",
    description="Search for a text pattern across files in the cloned repository.",
    params=[
        ToolParam("pattern", "string", "Text pattern to search for"),
        ToolParam("file_glob", "string", "File glob e.g. **/*.py (default: all files)", required=False),
    ]
)

# ---- Tool sets per agent ----

REFINEMENT_TOOLS = [
    JIRA_READ, JIRA_UPDATE_DESC, JIRA_STORY_POINTS,
    JIRA_COMMENT, GITHUB_SEARCH,
]

IMPLEMENTATION_SPEC_TOOLS = [
    JIRA_READ, JIRA_COMMENT, JIRA_TRANSITION,
    GITHUB_SEARCH, GITHUB_CREATE_ISSUE,
]

IMPLEMENTATION_CODING_TOOLS = [
    CODE_READ, CODE_WRITE, CODE_BASH, CODE_LIST, CODE_GREP,
    JIRA_COMMENT, JIRA_TRANSITION,
]


def get_tools_for_agent(agent_name: str) -> list[ToolDef]:
    """Return the correct tool set for an agent."""
    return {
        "refinement": REFINEMENT_TOOLS,
        "implementation_spec": IMPLEMENTATION_SPEC_TOOLS,
        "implementation_coding": IMPLEMENTATION_CODING_TOOLS,
    }.get(agent_name, [])
```

---

## The Generic SDK Runner

The runner itself is now fully provider-agnostic — it never imports any provider SDK directly:

```python
# framework/sdk_runner.py

from framework.providers.base import LLMProvider
from framework.providers.models import CanonicalMessage, ToolResult


class SDKRunner:
    """Provider-agnostic agentic loop."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider  # Injected — no provider import here

    async def run(self, agent, context) -> RunResult:
        prompt = agent.build_prompt(context)
        tools = get_tools_for_agent(agent.name)

        messages: list[CanonicalMessage] = [
            CanonicalMessage(role="user", text="Begin the workflow.")
        ]

        turn = 0
        while turn < agent.max_turns:
            turn += 1

            response = await self.provider.complete(
                system=prompt,
                messages=messages,
                tools=tools,
            )

            # Add assistant turn to history (canonical format)
            messages.append(CanonicalMessage(
                role="assistant",
                text=response.text,
                tool_calls=response.tool_calls,
            ))

            if not response.tool_calls:
                break  # Claude/GPT/Gemini is done

            # Execute tools
            tool_results = []
            for tc in response.tool_calls:
                result_text = await execute_tool(tc.name, tc.input, context)
                tool_results.append(ToolResult(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=result_text,
                ))

            # Feed results back (canonical format — provider converts when needed)
            messages.append(CanonicalMessage(
                role="user",
                tool_results=tool_results,
            ))

        # ... guardrails, return RunResult ...
```

---

## Configuration: How to Switch Providers

### Per-agent default (in agent class)

```python
class RefinementAgent(BaseAgent):
    provider = "anthropic"           # Default provider for this agent

class ImplementationAgent(BaseAgent):
    provider = "anthropic"           # Override with env var at runtime
```

### Override via environment variable

```bash
# Use Anthropic (default)
LLM_PROVIDER=anthropic uv run python run_agent.py refinement

# Use OpenAI GPT-4o
LLM_PROVIDER=openai uv run python run_agent.py refinement

# Use Google Gemini Flash (cheapest)
LLM_PROVIDER=google/gemini-2.0-flash uv run python run_agent.py refinement

# Use specific Anthropic model
LLM_PROVIDER=anthropic/claude-opus-4-20250514 uv run python run_agent.py refinement

# Use any LiteLLM-supported model (Mistral, Cohere, AWS Bedrock, etc.)
LLM_PROVIDER=litellm/mistral/mistral-large-latest uv run python run_agent.py refinement

# Keep Claude CLI for implementation (during transition)
LLM_PROVIDER=cli uv run python run_agent.py implementation
```

### In GitHub Actions workflow

```yaml
jobs:
  refinement:
    env:
      LLM_PROVIDER: ${{ vars.LLM_PROVIDER || 'anthropic' }}
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}       # optional
      GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}       # optional
```

### In `run_agent.py`

```python
def _get_runner(agent) -> SDKRunner | AgentRunner:
    provider_config = os.environ.get("LLM_PROVIDER", getattr(agent, "provider", "anthropic"))

    if provider_config == "cli":
        from framework.runner import AgentRunner
        return AgentRunner()
    else:
        from framework.providers import get_provider
        from framework.sdk_runner import SDKRunner
        return SDKRunner(provider=get_provider(provider_config))
```

---

## Cost Comparison Across Providers (per refinement run)

| Provider | Model | Input $/MTok | Output $/MTok | Est. cost/run |
|----------|-------|-------------|--------------|--------------|
| **Anthropic** | claude-sonnet-4 | $3.00 | $15.00 | ~$0.15 |
| **Anthropic** | claude-haiku-4 | $0.80 | $4.00 | ~$0.04 |
| **OpenAI** | gpt-4o | $2.50 | $10.00 | ~$0.13 |
| **OpenAI** | gpt-4o-mini | $0.15 | $0.60 | ~$0.008 |
| **Google** | gemini-2.0-flash | $0.075 | $0.30 | ~$0.004 |
| **Google** | gemini-2.5-pro | $1.25 | $10.00 | ~$0.06 |
| **Mistral** | mistral-large | $2.00 | $6.00 | ~$0.10 |
| **CLI (current)** | claude-sonnet-4 | included | included | ~$1.02* |

*CLI cost is the Claude Code subscription cost, not direct API billing.

**The cheapest option**: `google/gemini-2.0-flash` at ~$0.004/run = $0.40 per 100 refinements.

---

## Recommended Approach: LiteLLM

Rather than writing individual adapters for each provider, use **LiteLLM** as the normalization layer. LiteLLM already handles 100+ providers with one unified API.

```
Your Code (canonical ToolDef format)
    ↓
LiteLLMProvider adapter (thin wrapper, ~50 lines)
    ↓
LiteLLM library (handles all provider formats internally)
    ↓
Any of: Anthropic, OpenAI, Google, Mistral, AWS Bedrock, Azure, Cohere, Groq...
```

**Pros**: One adapter to maintain, supports any future provider automatically.  
**Cons**: Extra dependency, slightly less control over provider-specific features (e.g., Anthropic prompt caching).

Use **individual adapters** if you want prompt caching (Anthropic-specific) or fine-grained control.  
Use **LiteLLM** if you want maximum flexibility with minimum code.

---

## File Structure

```
framework/
├── providers/
│   ├── __init__.py             # get_provider() factory
│   ├── base.py                 # LLMProvider ABC
│   ├── models.py               # ToolDef, CanonicalMessage, LLMResponse, etc.
│   ├── anthropic_provider.py   # Anthropic Claude adapter
│   ├── openai_provider.py      # OpenAI GPT adapter
│   ├── google_provider.py      # Google Gemini adapter
│   └── litellm_provider.py     # LiteLLM universal adapter
│
├── tools/
│   ├── registry.py             # ToolDef definitions + get_tools_for_agent()
│   ├── executor.py             # execute_tool() dispatcher
│   ├── jira_tools.py           # Jira API implementations
│   ├── github_tools.py         # GitHub API implementations
│   └── coding_tools.py         # Filesystem + subprocess tools
│
└── sdk_runner.py               # Generic agentic loop (provider-agnostic)
```
