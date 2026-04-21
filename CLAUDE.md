# DevFlow Kit — Project Instructions

AI agents that turn Jira tickets into production-ready pull requests. Zero infrastructure — runs entirely on GitHub Actions.

## Quick Reference

```bash
uv sync --all-extras          # Install all deps (never use pip)
pytest tests/ -v              # Run tests
ruff format .                 # Format
ruff check .                  # Lint
python run_agent.py refinement  # Run an agent locally
```

## Architecture

```
agents/          → Concrete agent definitions (declarative, not algorithmic)
framework/       → Core: BaseAgent, runners, providers, tools, guardrails
  providers/     → LLM abstraction (Anthropic, OpenAI, Google)
  tools/         → Tool definitions and execution
mcp_server/      → MCP servers for Jira and GitHub integration
core/models.py   → Domain models (WorkItem, Spec, Task, etc.)
prompts/         → Agent system prompt templates (.md)
run_agent.py     → CLI entry point for all agents
repo-map.json    → Jira project → GitHub repo routing config
```

## Key Patterns

- **Agents are declarative**: they define tools, guardrails, and prompts — Claude makes all decisions. No algorithmic control flow inside agents.
- **Provider abstraction**: All LLM calls go through `framework/providers/base.py` (LLMProvider ABC). Never import `anthropic`/`openai`/`google` directly in runners or agents.
- **Canonical formats**: `ToolDef`, `LLMResponse`, `CanonicalMessage` in `framework/providers/base.py` — providers convert to/from these.
- **Two runners**: `AgentRunner` (CLI via `claude -p`) and `SDKRunner` (direct API calls). Selected by `LLM_PROVIDER` env var (`cli` vs `anthropic`/`openai`/`google`).
- **MCP for external tools**: Jira and GitHub APIs are exposed via MCP servers (`.mcp.json`), not called directly by agents.
- **Guardrails**: Post-execution validators in `framework/guardrail.py`. Always add guardrails when creating new agents.

## Adding a New Agent

1. Create `agents/your_agent.py` — subclass `BaseAgent`, declare tools/guardrails
2. Create `prompts/your-agent.md` — system prompt template
3. Add workflow `.github/workflows/your-agent.yml`
4. Add tests in `tests/`
5. Register in `run_agent.py`

## Adding a New LLM Provider

1. Create `framework/providers/your_provider.py` — implement `LLMProvider` ABC
2. Implement `complete()`, `convert_tools()`, `convert_messages()`
3. Register in `framework/providers/__init__.py` (`get_provider` factory)

## Configuration

- **`repo-map.json`**: Maps Jira projects/components → GitHub repos. Supports per-route `llm_provider` and `llm_model` overrides.
- **`LLM_PROVIDER` env var**: `cli` | `anthropic` | `openai` | `google` (optionally with model: `anthropic/claude-haiku-4-5-20251001`)
- **`.mcp.json`**: MCP server config for Jira and GitHub tools

## Code Style

- Python 3.12+, `uv` only (never pip)
- Ruff for formatting and linting (line-length: 100)
- Type hints on all function signatures
- Keep core dependencies minimal: only `httpx`, `pydantic`, `mcp`
- Provider SDKs are optional extras — guard imports accordingly

## Testing

- pytest with pytest-asyncio (asyncio_mode = "auto")
- Tests live in `tests/`
- Mock external calls (Jira, GitHub, LLM APIs) — never hit real services in tests
