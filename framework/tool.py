"""Tool — standard interface for CLI scripts that Claude calls via Bash.

A Tool wraps a Python CLI script and provides:
- A name and description (for the prompt)
- Argument definitions with descriptions (auto-generates usage docs)
- Output parsing (extract structured data from stdout)
- Environment variable requirements

The AgentRunner auto-generates tool documentation in the prompt
from Tool definitions. Adding a new tool automatically makes it
available to any agent that includes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolArg:
    """A single argument for a tool."""

    flag: str  # e.g., "--repo"
    description: str  # e.g., "Target repo (org/name)"
    required: bool = True
    default: str | None = None


@dataclass
class Tool:
    """Base class for all tools Claude can call.

    Subclass this or instantiate directly to define a tool.
    """

    name: str
    description: str
    script: str  # Relative path from repo root, e.g., "tools/create_github_issue.py"
    args: list[ToolArg] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)  # Required env vars

    def generate_usage(self) -> str:
        """Generate the bash usage example for the prompt."""
        parts = [f"python {self.script}"]
        for arg in self.args:
            if arg.required:
                parts.append(f'    {arg.flag} "<{arg.description}>"')
            else:
                default = f" (default: {arg.default})" if arg.default else ""
                parts.append(f'    {arg.flag} "<{arg.description}>"{default}')
        return " \\\n".join(parts)

    def generate_docs(self) -> str:
        """Generate full tool documentation for inclusion in agent prompts."""
        lines = [
            f"### {self.name}",
            self.description,
            "```bash",
            self.generate_usage(),
            "```",
        ]
        if self.args:
            lines.append("Arguments:")
            for arg in self.args:
                req = "required" if arg.required else "optional"
                lines.append(f"  {arg.flag}: {arg.description} ({req})")
        return "\n".join(lines)

    def parse_output(self, stdout: str) -> str:
        """Parse the tool's stdout into a usable value.

        Override this for tools that return structured data.
        Default: return stripped stdout.
        """
        return stdout.strip()


# ---------------------------------------------------------------------------
# Built-in tool definitions (Bash tools only — MCP handles Jira/GitHub)
# ---------------------------------------------------------------------------

resolve_repo = Tool(
    name="resolve_repo",
    description=(
        "Resolve a Jira project/component to a target GitHub repo and branch. "
        "This is custom routing logic — not available via MCP."
    ),
    script="tools/resolve_repo.py",
    args=[
        ToolArg("--project", "Jira project key", required=True),
        ToolArg("--component", "Jira component name", required=False, default=""),
    ],
)

# All built-in Bash tools (MCP tools are auto-discovered by Claude)
ALL_TOOLS = [resolve_repo]
