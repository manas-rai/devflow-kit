# Migration Guide: Claude CLI → Provider-Agnostic SDK

> **Status**: Planning — reference document for future migration  
> **Goal**: Replace Claude CLI with a direct SDK approach that supports multiple AI providers  
> **Scope**: Both refinement agent AND implementation agent  
> **Benefit**: ~85% token reduction, multi-provider support (Anthropic, OpenAI, Google), full control

---

## Table of Contents

1. [The Core Problem to Solve](#the-core-problem-to-solve)
2. [Current Architecture](#current-architecture)
3. [Target Architecture](#target-architecture)
4. [The `@claude` Problem — And the Solution](#the-claude-problem--and-the-solution)
5. [Provider Abstraction Layer](#provider-abstraction-layer)
6. [Tool Categories](#tool-categories)
7. [Implementation Agent: The New Flow](#implementation-agent-the-new-flow)
8. [Refinement Agent: Simple Case](#refinement-agent-simple-case)
9. [Full Code Walkthrough](#full-code-walkthrough)
10. [Token Cost Comparison](#token-cost-comparison)
11. [File Structure After Migration](#file-structure-after-migration)
12. [Migration Checklist](#migration-checklist)

---

## The Core Problem to Solve

### Current implementation agent flow

```
Step 1   Implementation Agent (Claude CLI)
         ├── Reads Jira ticket (via MCP Jira server)
         ├── Understands codebase (via repo map + search_code)
         ├── Creates a GitHub issue with the full technical spec
         └── Comments "@claude implement this..." on the GitHub issue
                │
                ▼
Step 2   Claude Code GitHub App (separate service)
         ├── Detects @claude mention on the GitHub issue
         ├── Spins up its own claude -p environment
         ├── Clones the repo to its sandbox
         ├── Reads the spec from the issue
         ├── Writes code files (Bash, Edit, Write tools)
         ├── Runs tests (Bash)
         ├── Creates branch + commits
         └── Opens a Pull Request
```

The **Step 2 functionality** (code writing, git ops, bash) is entirely inside the Claude Code GitHub App. If we drop the CLI, we lose this mechanism. We need to replace it.

### What we're replacing it with

The implementation agent itself becomes the "computer". Instead of delegating coding to the GitHub App, the **SDK runner does all of it** directly on the GitHub Actions runner VM:

```
Step 1+2 (MERGED) — Implementation Agent (SDK)
         ├── Reads Jira ticket (via Jira HTTP API tool)
         ├── Understands codebase (via GitHub API + repo map)
         ├── Creates a GitHub issue with the technical spec
         ├── Posts Jira comment with issue link
         ├── Transitions Jira to "In Progress"
         ├── Clones the repo (git subprocess)
         ├── Creates a feature branch (git subprocess)
         ├── In a loop with Claude API:
         │   ├── Claude: "Read this file" → we read it
         │   ├── Claude: "Write this code" → we write it
         │   ├── Claude: "Run these tests" → we run them
         │   └── Claude: "done" → we exit loop
         └── Creates a Pull Request (GitHub API)
```

The GitHub Actions runner already has git, Python, bash, and access to the internet. We execute these as Python subprocesses/HTTP calls. Claude just provides the intelligence.

---

## Current Architecture

```
GitHub Actions Runner
  └── run_agent.py
        ├── RefinementAgent
        │     └── subprocess("claude -p")
        │           ├── CLI system prompt (8K tok, uncontrollable)
        │           ├── Built-in tools (5K tok)
        │           ├── MCP Jira server (spawned subprocess)
        │           ├── MCP GitHub server (spawned subprocess)
        │           └── Agentic loop (~10 turns, ~340K tokens)
        │
        └── ImplementationAgent
              └── subprocess("claude -p")
                    ├── CLI system prompt (8K tok, uncontrollable)
                    ├── All tools (8K tok)
                    ├── MCP servers
                    └── Agentic loop (~10 turns)
                          └── @claude comment on GitHub issue
                                └── Claude Code GitHub App (Step 2)
                                      └── separate claude -p invocation
```

---

## Target Architecture

```
GitHub Actions Runner
  └── run_agent.py
        ├── RefinementAgent
        │     └── SDKRunner(provider="anthropic" | "openai" | "google")
        │           ├── Your system prompt (1K tok)
        │           ├── 4 HTTP tools only (0.5K tok)
        │           └── Agentic loop (~3-4 turns, ~50K tokens)
        │
        └── ImplementationAgent
              └── SDKRunner(provider="anthropic" | "openai" | "google")
                    ├── Your system prompt (2K tok)
                    ├── Tools: Jira API + GitHub API + Coding tools
                    └── Agentic loop (~15-20 turns)
                          ├── Jira read/write (HTTP)
                          ├── GitHub issue creation (HTTP)
                          ├── File read/write (filesystem)
                          ├── Bash execution (subprocess)
                          └── Git operations (subprocess → GitHub API)
```

---

## The `@claude` Problem — And the Solution

### What `@claude` currently does

The Claude Code GitHub App is triggered by `@claude` comments. When it sees one, it:
1. Clones the repo
2. Reads the issue spec
3. Uses `claude -p` with all coding tools (Bash, Edit, Write, Read, Grep, Glob)
4. Creates branch, commits, opens PR

This is essentially a **managed code execution environment** provided as a service by Anthropic.

### Why we can reproduce it

The GitHub Actions runner already is a code execution environment with:
- ✅ `git` installed
- ✅ `python` installed
- ✅ `bash` available
- ✅ Full filesystem access
- ✅ Network access (Anthropic API, GitHub API, Jira API)
- ✅ The repo can be cloned

We implement these as **Python tool functions** that the SDK runner calls:

```
Claude says:     We run:
read_file()   →  Path(file).read_text()
write_file()  →  Path(file).write_text()
run_bash()    →  subprocess.run(["bash", "-c", cmd])
git_commit()  →  subprocess.run(["git", "commit", ...])
create_pr()   →  httpx.post("https://api.github.com/repos/.../pulls")
```

### Security consideration

The bash execution tool should run in the **cloned repo directory only**. We validate that paths stay within the repo root before any file operation or command execution.

---

## Provider Abstraction Layer

The key architectural addition: a `LLMProvider` interface that all runners use. Swap the provider by changing one config value.

```python
# framework/providers/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ProviderResponse:
    """Normalized response from any LLM provider."""
    text: str | None
    tool_calls: list[dict]  # [{name, id, input}, ...]
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens"


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> ProviderResponse:
        """Send a completion request and return a normalized response."""
        ...

    @abstractmethod
    def format_tool_result(
        self,
        tool_use_id: str,
        content: str,
    ) -> dict:
        """Format a tool result message for this provider's API format."""
        ...
```

```python
# framework/providers/anthropic_provider.py

import anthropic
from framework.providers.base import LLMProvider, ProviderResponse


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY
        self.model = model

    async def complete(self, system, messages, tools, max_tokens=4096) -> ProviderResponse:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
        )
        usage = response.usage
        tool_calls = [
            {"id": b.id, "name": b.name, "input": b.input}
            for b in response.content if b.type == "tool_use"
        ]
        text = next((b.text for b in response.content if b.type == "text"), None)
        return ProviderResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=usage.input_tokens + getattr(usage, "cache_creation_input_tokens", 0),
            output_tokens=usage.output_tokens,
            cached_tokens=getattr(usage, "cache_read_input_tokens", 0),
            stop_reason=response.stop_reason,
        )

    def format_tool_result(self, tool_use_id, content):
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
        }
```

```python
# framework/providers/openai_provider.py
# (Add later — same interface, different API calls)

import openai
from framework.providers.base import LLMProvider, ProviderResponse


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str = "gpt-4o"):
        self.client = openai.OpenAI()  # Uses OPENAI_API_KEY
        self.model = model

    async def complete(self, system, messages, tools, max_tokens=4096) -> ProviderResponse:
        # OpenAI uses a different format — normalize it here
        oai_messages = [{"role": "system", "content": system}] + messages
        oai_tools = [{"type": "function", "function": t} for t in tools]

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=oai_messages,
            tools=oai_tools,
        )

        choice = response.choices[0]
        tool_calls = []
        if choice.message.tool_calls:
            import json
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": json.loads(tc.function.arguments),
                })

        return ProviderResponse(
            text=choice.message.content,
            tool_calls=tool_calls,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            cached_tokens=getattr(response.usage, "cached_tokens", 0),
            stop_reason="tool_use" if tool_calls else "end_turn",
        )

    def format_tool_result(self, tool_use_id, content):
        return {
            "role": "tool",
            "tool_call_id": tool_use_id,
            "content": content,
        }
```

```python
# framework/providers/google_provider.py
# (Add later — Google Gemini API)

import google.generativeai as genai
from framework.providers.base import LLMProvider, ProviderResponse


class GoogleProvider(LLMProvider):
    def __init__(self, model: str = "gemini-2.0-flash"):
        genai.configure()  # Uses GOOGLE_API_KEY
        self.model = genai.GenerativeModel(model)

    async def complete(self, system, messages, tools, max_tokens=4096) -> ProviderResponse:
        # Google API normalization here
        ...
```

```python
# framework/providers/__init__.py

def get_provider(name: str = "anthropic"):
    """Factory: return the correct provider by name."""
    if name == "anthropic":
        from framework.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    elif name == "openai":
        from framework.providers.openai_provider import OpenAIProvider
        return OpenAIProvider()
    elif name == "google":
        from framework.providers.google_provider import GoogleProvider
        return GoogleProvider()
    else:
        raise ValueError(f"Unknown provider: {name}. Options: anthropic, openai, google")
```

---

## Tool Categories

Tools split into two groups:

### Group 1: API Tools (stateless HTTP)
> Used by both refinement and implementation agents

```python
# framework/tools/jira_tools.py
async def read_jira_ticket(issue_key: str) -> str: ...
async def update_jira_description(issue_key: str, description: str) -> str: ...
async def update_jira_story_points(issue_key: str, story_points: float) -> str: ...
async def post_jira_comment(issue_key: str, comment: str) -> str: ...
async def transition_jira_ticket(issue_key: str, transition: str) -> str: ...

# framework/tools/github_tools.py
async def search_code(repo: str, query: str) -> str: ...
async def create_technical_issue(repo: str, title: str, body: str) -> str: ...
async def create_branch(repo: str, branch: str, base: str) -> str: ...
async def create_pull_request(repo: str, title: str, body: str, head: str, base: str) -> str: ...
async def post_github_comment(repo: str, issue_number: int, comment: str) -> str: ...
```

### Group 2: Coding Tools (filesystem + subprocess)
> Used ONLY by the implementation agent
> Replaces: Bash, Read, Write, Edit, Grep, Glob from Claude CLI

```python
# framework/tools/coding_tools.py

import subprocess
from pathlib import Path


# Security: all operations validated to stay within repo_root
REPO_ROOT: Path | None = None


def set_repo_root(path: Path):
    global REPO_ROOT
    REPO_ROOT = path


def _validate_path(file_path: str) -> Path:
    """Ensure path is within repo root (prevent path traversal)."""
    full = (REPO_ROOT / file_path).resolve()
    if not str(full).startswith(str(REPO_ROOT.resolve())):
        raise ValueError(f"Path {file_path} is outside the repo root")
    return full


async def read_file(path: str) -> str:
    """Read a file from the cloned repo."""
    return _validate_path(path).read_text(encoding="utf-8")


async def write_file(path: str, content: str) -> str:
    """Write content to a file in the cloned repo."""
    full_path = _validate_path(path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")
    return f"Written: {path}"


async def list_files(directory: str = ".") -> str:
    """List files in a directory."""
    full = _validate_path(directory)
    files = [str(f.relative_to(REPO_ROOT)) for f in full.rglob("*") if f.is_file()]
    return "\n".join(files[:100])  # Cap at 100 files


async def search_in_repo(pattern: str, file_glob: str = "**/*.py") -> str:
    """Grep for a pattern in the cloned repo files."""
    results = []
    for f in REPO_ROOT.glob(file_glob):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern in line:
                    results.append(f"{f.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
        except Exception:
            continue
    return "\n".join(results[:50]) if results else f"No matches for '{pattern}'"


async def run_bash(command: str, timeout: int = 60) -> str:
    """Run a bash command in the cloned repo directory."""
    result = subprocess.run(
        command,
        shell=True,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = result.stdout
    if result.returncode != 0:
        output += f"\n[exit code {result.returncode}]\n{result.stderr}"
    return output[:5000]  # Cap output


async def git_status() -> str:
    """Get current git status."""
    return await run_bash("git status --short")


async def git_diff() -> str:
    """Get current git diff."""
    return await run_bash("git diff")


async def git_add_and_commit(message: str) -> str:
    """Stage all changes and commit."""
    add = await run_bash("git add -A")
    commit = await run_bash(f'git commit -m "{message}"')
    return f"{add}\n{commit}"


async def git_push(branch: str) -> str:
    """Push branch to origin."""
    return await run_bash(f"git push origin {branch}")
```

---

## Implementation Agent: The New Flow

### Step 1: Spec phase (same as refinement — API tools only)

```
Read Jira ticket     → jira_tools.read_jira_ticket()
Read repo structure  → repo_map (injected into prompt)
Search specific code → github_tools.search_code()
Create GitHub issue  → github_tools.create_technical_issue()
Post Jira comment    → jira_tools.post_jira_comment()
Transition ticket    → jira_tools.transition_jira_ticket()
```

### Step 2: Coding phase (coding tools — filesystem + subprocess)

The implementation agent's prompt is split into two phases. After creating the GitHub issue, the SDK runner **clones the repo** and gives Claude access to the coding tools:

```python
# In sdk_runner.py — for implementation agent

import shutil, tempfile

async def _run_implementation(agent, context, provider):
    # Phase 1: Spec (API tools only, ~3 turns)
    spec_result = await _spec_phase(agent, context, provider)
    github_issue_url = spec_result.get("github_issue_url")

    # Clone the repo for Phase 2
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        _clone_repo(context.target_repo, context.target_branch, tmp_dir)
        coding_tools.set_repo_root(tmp_dir)

        # Create feature branch
        branch_name = f"devflow/{context.issue_key.lower()}"
        await coding_tools.run_bash(f"git checkout -b {branch_name}")

        # Phase 2: Coding (coding tools + API tools, ~15 turns)
        await _coding_phase(agent, context, provider, spec_result, tmp_dir)

        # Push and create PR
        await coding_tools.git_push(branch_name)
        pr_url = await github_tools.create_pull_request(
            repo=context.target_repo,
            title=f"[{context.issue_key}] {context.summary}",
            body=f"Closes {github_issue_url}\n\nImplemented by DevFlow Kit.",
            head=branch_name,
            base=context.target_branch,
        )
        await jira_tools.post_jira_comment(
            context.issue_key, f"PR opened: {pr_url}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
```

### Prompt structure for implementation agent

The implementation prompt is updated to remove the `@claude` trick and instead describe the two phases directly:

```markdown
You are the DevFlow Kit implementation agent.

## Your Mission
You will:
1. Read the approved Jira ticket and repo structure
2. Create a detailed technical GitHub issue (tech spec)
3. Update Jira with the issue link
4. Write the code changes using the coding tools available to you
5. Commit and the runner will open a PR

## IMPORTANT: You have two sets of tools

### Phase 1 — Planning tools (use first)
- `read_jira_ticket` — Read business requirements
- `create_technical_issue` — Create the tech spec issue
- `post_jira_comment` — Notify team
- `transition_jira_ticket` — Move to In Progress
- `search_code` — Search codebase

### Phase 2 — Coding tools (use after creating the issue)
- `read_file(path)` — Read any file in the repo
- `write_file(path, content)` — Write or overwrite files
- `list_files(directory)` — List files in a directory
- `search_in_repo(pattern)` — Grep across the codebase
- `run_bash(command)` — Run tests, install deps, etc.

## Execution Sequence
1. Call `read_jira_ticket`
2. Review the repo map below
3. Call `create_technical_issue` with the full technical spec
4. Call `post_jira_comment` and `transition_jira_ticket`
5. Call `read_file` to understand the files you need to change
6. Implement the changes using `write_file`
7. Call `run_bash("python -m pytest tests/ -q")` to verify tests pass
8. Done — the runner will commit and open the PR
```

---

## Refinement Agent: Simple Case

No changes to the business logic — just replaces MCP servers with direct HTTP calls:

```
Current:  MCP Jira server → TCP → jira_server.py → httpx → Jira API
New:      jira_tools.py → httpx → Jira API (same call, no middleman)
```

Expected: **340K → 50K tokens** (85% reduction), **$1.02 → $0.15 per run**.

---

## Full Code Walkthrough

### `framework/sdk_runner.py` (the core)

```python
"""SDKRunner — provider-agnostic agentic loop replacing Claude CLI."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from framework.base_agent import AgentContext, BaseAgent
from framework.runner import RunResult, ToolCall
from framework.providers import get_provider
from framework.tools import get_tools_for_agent, execute_tool


class SDKRunner:
    def __init__(self, provider: str = "anthropic"):
        self.provider = get_provider(provider)

    async def run(self, agent: BaseAgent, context: AgentContext) -> RunResult:
        start_time = time.time()
        await agent.on_start(context)

        prompt = agent.build_prompt(context)

        # Load correct tool schemas for this agent type
        tools = get_tools_for_agent(agent.name)

        messages = [{"role": "user", "content": "Begin the workflow."}]

        total_in, total_out, total_cached = 0, 0, 0
        all_calls = []
        full_log = ""
        turn = 0

        while turn < agent.max_turns:
            turn += 1

            # Call LLM
            response = await self.provider.complete(
                system=prompt,
                messages=messages,
                tools=tools,
            )

            total_in += response.input_tokens
            total_out += response.output_tokens
            total_cached += response.cached_tokens

            print(
                f"  Turn {turn}: {response.input_tokens:,} in / "
                f"{response.output_tokens:,} out / "
                f"{response.cached_tokens:,} cached",
                file=sys.stderr,
            )

            if response.text:
                full_log += response.text + "\n"

            if not response.tool_calls:
                break  # Claude is done

            # Add assistant message to history
            messages.append({"role": "assistant", "content": _build_assistant_content(response)})

            # Execute tools and collect results
            tool_results = []
            for tc in response.tool_calls:
                print(f"    → {tc['name']}({list(tc['input'].keys())})", file=sys.stderr)
                result = await execute_tool(tc["name"], tc["input"], context)
                full_log += f"\n[{tc['name']}]: {result[:300]}\n"

                all_calls.append(ToolCall(
                    tool_name=tc["name"],
                    script=tc["name"],
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                ))

                tool_results.append(
                    self.provider.format_tool_result(tc["id"], result)
                )

            # Feed results back
            messages.append({"role": "user", "content": tool_results})

            if response.stop_reason == "end_turn":
                break

        print(
            f"\n📊 Tokens: {total_in:,} input / {total_out:,} output"
            f" / {total_cached:,} cached ({turn} turns)",
            file=sys.stderr,
        )

        # Guardrails
        guardrail_results = []
        failed_errors = []
        for g in agent.guardrails:
            r = g.check(full_log, context.__dict__)
            guardrail_results.append(r)
            if not r.passed and g.severity == "error":
                failed_errors.append(f"[{g.name}] {r.message}")

        duration = time.time() - start_time
        status = "failure" if failed_errors else "success"

        if failed_errors:
            await agent.on_failure(context, "\n".join(failed_errors))
        else:
            await agent.on_success(context, full_log)

        return RunResult(
            status=status,
            execution_log=full_log,
            tool_calls=all_calls,
            guardrail_results=guardrail_results,
            attempts=1,
            duration_seconds=duration,
            error="\n".join(failed_errors),
            input_tokens=total_in,
            output_tokens=total_out,
        )
```

### `run_agent.py` — routing

```python
def _get_runner(agent: BaseAgent) -> AgentRunner | SDKRunner:
    """Return the correct runner. Env var overrides agent config."""
    provider = os.environ.get("LLM_PROVIDER", getattr(agent, "provider", "cli"))

    if provider == "cli":
        from framework.runner import AgentRunner
        return AgentRunner()
    else:
        # provider is "anthropic", "openai", or "google"
        from framework.sdk_runner import SDKRunner
        return SDKRunner(provider=provider)
```

Set `LLM_PROVIDER=anthropic` (or `openai` / `google`) in the GitHub Actions workflow to switch providers without code changes.

### Agent config

```python
class RefinementAgent(BaseAgent):
    name = "refinement"
    provider = "anthropic"  # Default provider for this agent
    ...

class ImplementationAgent(BaseAgent):
    name = "implementation"
    provider = "anthropic"  # Can switch to "openai" for testing
    ...
```

---

## Token Cost Comparison

| Agent | CLI (current) | SDK (Anthropic) | SDK (OpenAI GPT-4o) |
|-------|--------------|-----------------|---------------------|
| **Refinement** | ~340K input | ~50K | ~50K |
| **Refinement cost** | ~$1.02 | ~$0.15 | ~$0.13 |
| **Implementation** | ~500K input | ~150K | ~150K |
| **Implementation cost** | ~$1.50 | ~$0.45 | ~$0.40 |
| **Per full cycle** | ~$2.52 | ~$0.60 | ~$0.53 |
| **Monthly (100 cycles)** | ~$252 | ~$60 | ~$53 |

---

## File Structure After Migration

```
devflow-kit/
├── framework/
│   ├── base_agent.py          # Add: provider field
│   ├── guardrail.py           # Unchanged
│   ├── runner.py              # Keep: CLI runner (fallback / legacy)
│   ├── sdk_runner.py          # NEW: Provider-agnostic agentic loop
│   │
│   ├── providers/
│   │   ├── __init__.py        # NEW: get_provider() factory
│   │   ├── base.py            # NEW: LLMProvider ABC + ProviderResponse
│   │   ├── anthropic_provider.py  # NEW: Anthropic SDK
│   │   ├── openai_provider.py     # NEW: OpenAI SDK
│   │   └── google_provider.py     # NEW: Google Gemini SDK
│   │
│   └── tools/
│       ├── __init__.py        # NEW: get_tools_for_agent() + execute_tool()
│       ├── jira_tools.py      # NEW: Jira HTTP API functions
│       ├── github_tools.py    # NEW: GitHub HTTP API functions
│       └── coding_tools.py    # NEW: read_file, write_file, run_bash, git ops
│
├── agents/
│   ├── refinement.py          # Update: provider = "anthropic"
│   └── implementation.py      # Update: provider = "anthropic", new prompt
│
├── prompts/
│   ├── refine.md              # Minor update: remove MCP resource references
│   └── implement.md           # Major rewrite: no @claude, direct coding tools
│
├── run_agent.py               # Update: _get_runner() routing logic
├── pyproject.toml             # Add: anthropic, openai, google-generativeai
│
└── docs/
    └── sdk-migration-guide.md # This file
```

---

## Migration Checklist

### Phase 0 — Prerequisite
- [ ] Get `ANTHROPIC_API_KEY` from console.anthropic.com
- [ ] Add to GitHub Actions secrets
- [ ] `uv add "anthropic>=0.40" "openai>=1.0" "google-generativeai>=0.8"`

### Phase 1 — Provider layer (2-3 days)
- [ ] Create `framework/providers/base.py` — `LLMProvider` ABC + `ProviderResponse`
- [ ] Create `framework/providers/anthropic_provider.py`
- [ ] Create `framework/providers/__init__.py` with factory
- [ ] Write unit tests for provider normalization
- [ ] Add `OpenAIProvider` and `GoogleProvider` stubs (can be empty `pass` initially)

### Phase 2 — Tool layer (2-3 days)
- [ ] Create `framework/tools/jira_tools.py` — port from `mcp_server/jira_client.py`
- [ ] Create `framework/tools/github_tools.py` — port from `mcp_server/github_server.py`
- [ ] Create `framework/tools/coding_tools.py` — new: read_file, write_file, run_bash, git
- [ ] Create `framework/tools/__init__.py` — tool registry + `get_tools_for_agent()`
- [ ] Write unit tests with `httpx_mock` for all API tools

### Phase 3 — SDK Runner (1-2 days)
- [ ] Create `framework/sdk_runner.py` with the generic agentic loop
- [ ] Update `run_agent.py` with `_get_runner()` routing
- [ ] Add `provider` field to `BaseAgent`
- [ ] Write integration test with mocked Anthropic API
- [ ] Test with `LLM_PROVIDER=cli` to verify fallback still works

### Phase 4 — Refinement agent migration (1 day)
- [ ] Set `provider = "anthropic"` on `RefinementAgent`
- [ ] Update `prompts/refine.md` to remove MCP resource URI references
- [ ] Run against a test Jira ticket
- [ ] Compare token counts vs CLI baseline
- [ ] Monitor for 1 week

### Phase 5 — Implementation agent migration (3-5 days)
- [ ] Rewrite `prompts/implement.md` — remove `@claude` trigger, add coding tool instructions
- [ ] Implement `coding_tools.py` fully (read, write, bash, git)
- [ ] Add repo clone/cleanup logic to `sdk_runner.py` for implementation agent
- [ ] Test on a small, isolated Jira ticket
- [ ] Verify PR is created correctly
- [ ] Compare output quality vs CLI + Claude Code GitHub App

### Phase 6 — Cleanup
- [ ] Remove `.mcp.json` (no longer needed)
- [ ] Remove `mcp_server/` directory (logic now in `framework/tools/`)
- [ ] Remove `claude login` step from GitHub Actions workflow
- [ ] Update README
- [ ] Archive `docs/sdk-migration-guide.md` as completed

---

## Key Risk: Implementation Quality

The biggest risk in Phase 5 is **code quality**. The Claude Code GitHub App has years of tuning for software engineering tasks. Our custom coding loop needs to:

1. **Give Claude enough context** — the full file contents, not just repo map
2. **Handle errors** — if tests fail, feed the error back and let Claude try again
3. **Keep changes focused** — the spec must be very specific to prevent scope creep

Mitigation: Start with a simple, well-defined Jira ticket as the test case.
