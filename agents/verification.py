"""VerificationAgent — automatically checks PRs against requirements.

Triggered by CI completion or PR review requests.
Pulls the branch, runs the test suite, and compares the actual implementations
against the Acceptance Criteria defined in the `Spec`.
"""

from __future__ import annotations

import os
import sys

from devflow_core.models import Spec, VerificationResult
from framework.base_agent import AgentContext, BaseAgent
from framework.guardrail import NoErrorsInOutput


class VerificationAgent(BaseAgent):
    name = "verification"
    prompt_template = "prompts/verify.md"

    # We provide tools for reading code and running bash commands (like pytest)
    # The actual tools will be defined in framework/tool.py or via MCP.
    tools = [] # To be populated with code search and terminal runner tools

    guardrails = [
        NoErrorsInOutput(),
    ]

    max_turns = 15
    retry_count = 1

    async def on_start(self, context: AgentContext) -> None:
        """Log that V&V has started."""
        print(f"🔍 Starting Verification & Validation for {context.issue_key}...", file=sys.stderr)

    async def on_success(self, context: AgentContext, execution_log: str) -> None:
        """Parse the structured VerificationResult output by Claude and post to GitHub PR."""
        # TODO: Post the result back to the PR as a review using github_client
        print(f"✅ V&V completed successfully for {context.issue_key}.", file=sys.stderr)

    async def on_failure(self, context: AgentContext, error: str) -> None:
        """Post failure to the PR."""
        print(f"❌ V&V failed: {error}", file=sys.stderr)
