"""RefinementAgent — the core entry point for all DevFlow Kit work.

This agent analyzes a Jira ticket, understands the target codebase,
and takes whatever actions are needed: creating a single @claude issue,
or decomposing into parallel subtasks. Claude makes all decisions.

This file is purely declarative — it defines WHAT the agent is:
  - Which prompt to use
  - Which tools Claude gets
  - Which guardrails to enforce
  - What happens on start/success/failure

It does NOT define HOW the agent thinks. That's in prompts/refine.md.
"""

from __future__ import annotations

import os
import sys

import httpx

from framework.base_agent import AgentContext, BaseAgent
from framework.guardrail import (
    MaxSubtasks,
    MustCreateGitHubIssue,
    MustUpdateJira,
    NoErrorsInOutput,
)
from framework.tool import resolve_repo


class RefinementAgent(BaseAgent):
    name = "refinement"
    prompt_template = "prompts/refine.md"

    # Bash tools only — Jira and GitHub are handled by MCP servers
    tools = [resolve_repo]

    guardrails = [
        MustCreateGitHubIssue(),
        MustUpdateJira(),
        MaxSubtasks(5),
        NoErrorsInOutput(),
    ]

    max_turns = 30
    retry_count = 1

    async def on_start(self, context: AgentContext) -> None:
        """Post a comment to Jira that refinement has started."""
        try:
            base_url = context.jira_base_url.rstrip("/")
            auth = (
                os.environ.get("JIRA_USER_EMAIL", ""),
                os.environ.get("JIRA_API_TOKEN", ""),
            )
            payload = {
                "body": {
                    "version": 1,
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        f"🤖 DevFlow Kit: Analyzing ticket and reading "
                                        f"{context.target_repo}..."
                                    ),
                                }
                            ],
                        }
                    ],
                }
            }
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{base_url}/rest/api/3/issue/{context.issue_key}/comment",
                    auth=auth,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except Exception as e:
            print(f"on_start: Jira comment failed: {e}", file=sys.stderr)

    async def on_failure(self, context: AgentContext, error: str) -> None:
        """Post the failure to Jira so the team knows."""
        try:
            base_url = context.jira_base_url.rstrip("/")
            auth = (
                os.environ.get("JIRA_USER_EMAIL", ""),
                os.environ.get("JIRA_API_TOKEN", ""),
            )
            run_url = (
                f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}"
                f"/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
            )
            payload = {
                "body": {
                    "version": 1,
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        f"❌ DevFlow Kit: Refinement failed\n\n"
                                        f"Error: {error[:300]}\n"
                                        f"Actions log: {run_url}"
                                    ),
                                }
                            ],
                        }
                    ],
                }
            }
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{base_url}/rest/api/3/issue/{context.issue_key}/comment",
                    auth=auth,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except Exception as e:
            print(f"on_failure: Jira comment failed: {e}", file=sys.stderr)
