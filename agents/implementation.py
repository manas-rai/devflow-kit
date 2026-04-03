"""ImplementationAgent — creates GitHub issues and triggers Claude Code.

Triggered when a PM approves a refined ticket by moving it to "Ready for Dev".
Reads the technical spec from the Jira description, creates a GitHub issue
in the target repo, and triggers Claude Code via @claude comment.

This agent does NOT implement code itself — Claude Code GitHub App handles
actual implementation (branch, code, PR).
"""

from __future__ import annotations

import os
import sys

import httpx

from framework.base_agent import AgentContext, BaseAgent
from framework.guardrail import (
    MustCreateGitHubIssue,
    MustUpdateJira,
    NoErrorsInOutput,
)
from framework.tool import resolve_repo


class ImplementationAgent(BaseAgent):
    name = "implementation"
    prompt_template = "prompts/implement.md"

    tools = [resolve_repo]

    guardrails = [
        MustCreateGitHubIssue(),  # Must create the GitHub issue
        MustUpdateJira(),          # Must post Jira comment with issue link
        NoErrorsInOutput(),
    ]

    # Only allow implementation-related tools (enforced at Claude CLI level)
    allowed_tools = [
        "mcp__devflow-github__create_technical_issue",
        "mcp__devflow-github__update_technical_issue",
        "mcp__devflow-github__post_github_comment",
        "mcp__devflow-github__search_code",
        "mcp__devflow-jira__post_jira_comment",
        "mcp__devflow-jira__transition_jira_ticket",
        "Read", "Grep", "Glob", "WebSearch", "WebFetch",
        "Bash", "ReadMcpResourceTool", "ListMcpResourcesTool",
    ]

    max_turns = 10  # Repo map provides upfront context; 10 turns is sufficient
    retry_count = 1

    async def on_start(self, context: AgentContext) -> None:
        """Post a comment to Jira that implementation has started."""
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
                                        f"🤖 DevFlow Kit: Implementation started. "
                                        f"Creating branch and PR in {context.target_repo}..."
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
        """Post the failure to Jira."""
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
                                        f"❌ DevFlow Kit: Implementation failed\n\n"
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
