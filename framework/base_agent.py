"""BaseAgent — abstract definition of a DevFlow Kit agent.

An agent is a declarative definition:
  - Which prompt template to use
  - Which tools are available
  - Which guardrails to enforce
  - Retry and turn configuration
  - Lifecycle hooks (on_start, on_success, on_failure)

An agent does NOT contain decision logic. Claude makes all decisions.
The agent class defines the *structure* — what tools Claude gets,
what rules are enforced, and what happens on success/failure.

Usage:
    class MyAgent(BaseAgent):
        name = "my_agent"
        prompt_template = "prompts/my_agent.md"
        tools = [create_github_issue, post_jira_comment]
        guardrails = [MustCreateGitHubIssue()]
        max_turns = 30
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from framework.guardrail import Guardrail
from framework.tool import Tool
from devflow_core.models import WorkItem, Spec


@dataclass
class AgentContext:
    """Runtime context passed to the agent — the inputs it works with."""

    issue_key: str = ""
    project_key: str = ""
    component: str = ""
    summary: str = ""
    description: str = ""
    jira_base_url: str = ""
    target_repo: str = ""
    target_branch: str = "main"
    
    # Core Domain Models
    work_item: WorkItem | None = None
    spec: Spec | None = None
    
    extra: dict = field(default_factory=dict)

    def to_template_vars(self) -> dict[str, str]:
        """Convert context to template variable replacements."""
        return {
            "{{issue_key}}": self.issue_key,
            "{{project_key}}": self.project_key,
            "{{component}}": self.component,
            "{{summary}}": self.summary,
            "{{description}}": self.description or "No description provided.",
            "{{jira_base_url}}": self.jira_base_url.rstrip("/"),
            "{{target_repo}}": self.target_repo,
            "{{target_branch}}": self.target_branch,
        }


class BaseAgent:
    """Abstract base class for all DevFlow Kit agents.

    Subclass this to create a concrete agent. Override lifecycle hooks
    as needed — the defaults are no-ops.
    """

    # --- Required: override these in subclasses ---
    name: str = "unnamed_agent"
    prompt_template: str = ""  # Path relative to repo root

    # --- Optional: configure these ---
    tools: list[Tool] = []
    guardrails: list[Guardrail] = []
    max_turns: int = 30
    retry_count: int = 1  # How many times to retry on guardrail failure
    verbose: bool = True

    def load_prompt_template(self) -> str:
        """Load the raw prompt template from file."""
        path = Path(__file__).parent.parent / self.prompt_template
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text()

    def build_prompt(self, context: AgentContext) -> str:
        """Build the complete prompt: template + tool docs + context vars.

        The framework assembles:
        1. The agent's prompt template (identity, instructions, rules)
        2. Auto-generated tool documentation (from Tool definitions)
        3. Context variable replacement (issue key, summary, etc.)

        The tool docs section is generated automatically — when you add
        a new tool to the agent's tools list, it appears in the prompt
        without any prompt editing.
        """
        template = self.load_prompt_template()

        # Replace context variables
        prompt = template
        for placeholder, value in context.to_template_vars().items():
            prompt = prompt.replace(placeholder, value)

        # Auto-generate tool docs section if the prompt has {{tool_docs}}
        if "{{tool_docs}}" in prompt:
            tool_docs = "\n\n".join(tool.generate_docs() for tool in self.tools)
            prompt = prompt.replace("{{tool_docs}}", tool_docs)

        return prompt

    def get_retry_prompt(self, original_prompt: str, failure_message: str) -> str:
        """Build a retry prompt when guardrails fail.

        Appends the failure message to the original prompt so Claude
        knows what went wrong and can correct course.
        """
        return (
            f"{original_prompt}\n\n"
            f"---\n"
            f"IMPORTANT: Your previous attempt failed a guardrail check:\n"
            f"{failure_message}\n\n"
            f"Please try again, making sure to address this issue."
        )

    # --- Lifecycle hooks (override as needed) ---

    async def on_start(self, context: AgentContext) -> None:
        """Called before the agent runs. Use for setup or notifications."""
        pass

    async def on_success(self, context: AgentContext, execution_log: str) -> None:
        """Called after a successful run (all guardrails passed)."""
        pass

    async def on_failure(self, context: AgentContext, error: str) -> None:
        """Called when the agent fails after all retries."""
        pass

    async def on_retry(self, context: AgentContext, attempt: int, failure: str) -> None:
        """Called before each retry attempt."""
        pass
