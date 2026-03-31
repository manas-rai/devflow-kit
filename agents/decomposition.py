"""DecompositionAgent — breaks a large Spec/Epic into parallel GitHub issues.

When an Epic is refined, it is too large for a single Claude Code session
to implement perfectly. The Decomposition Agent uses the `TaskGraph` domain model
concept to split the work into 3-4 distinct, non-overlapping GitHub issues.

This triggers 3-4 parallel Implementation Agents, massively speeding up delivery.
"""

from __future__ import annotations

import os
import sys

from framework.base_agent import AgentContext, BaseAgent
from framework.guardrail import MustCreateGitHubIssue


class DecompositionAgent(BaseAgent):
    name = "decomposition"
    prompt_template = "prompts/decompose.md"

    # Needs to be able to create GitHub issues and push Spec parts to them
    # tools will be injected via framework if requested.
    tools = [] # To be populated with github_issue MCP tools

    guardrails = [
        MustCreateGitHubIssue(),
    ]

    max_turns = 10
    retry_count = 1

    async def on_start(self, context: AgentContext) -> None:
        """Log that Decomposition has started."""
        print(f"🧩 Starting Decomposition for {context.issue_key}...", file=sys.stderr)

    async def on_success(self, context: AgentContext, execution_log: str) -> None:
        print(f"✅ Decomposition completed for {context.issue_key}. Parallel issues created.", file=sys.stderr)

    async def on_failure(self, context: AgentContext, error: str) -> None:
        print(f"❌ Decomposition failed: {error}", file=sys.stderr)
