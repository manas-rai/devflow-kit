#!/usr/bin/env python3
"""Entry point for running agents from GitHub Actions workflows.

Usage:
    python run_agent.py refinement
    python run_agent.py sync

This is pure wiring — reads env vars, creates context, picks the
agent, hands it to the runner. Zero decision logic.
"""

from __future__ import annotations

import asyncio
import os
import sys

from framework.base_agent import AgentContext
from framework.runner import AgentRunner


def resolve_target_repo() -> tuple[str, str]:
    """Read repo-map.json and resolve the target repo from env vars."""
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "tools/resolve_repo.py",
            "--project",
            os.environ.get("PROJECT_KEY", ""),
            "--component",
            os.environ.get("COMPONENT", ""),
        ],
        capture_output=True,
        text=True,
    )
    parts = result.stdout.strip().split()
    return (parts[0], parts[1]) if len(parts) >= 2 else ("", "main")


async def run_refinement() -> None:
    from agents.refinement import RefinementAgent

    repo, branch = resolve_target_repo()

    context = AgentContext(
        issue_key=os.environ.get("ISSUE_KEY", ""),
        project_key=os.environ.get("PROJECT_KEY", ""),
        component=os.environ.get("COMPONENT", ""),
        summary=os.environ.get("SUMMARY", ""),
        description=os.environ.get("DESCRIPTION", ""),
        jira_base_url=os.environ.get("JIRA_BASE_URL", ""),
        target_repo=repo,
        target_branch=branch,
    )

    agent = RefinementAgent()
    runner = AgentRunner()
    result = await runner.run(agent, context)

    print(f"\n{'='*60}")
    print(f"Agent: {agent.name}")
    print(f"Status: {result.status}")
    print(f"Attempts: {result.attempts}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Tool calls: {len(result.tool_calls)}")
    for tc in result.tool_calls:
        print(f"  - {tc.tool_name}")
    if result.error:
        print(f"Error: {result.error}")
    print("=" * 60)

    if not result.succeeded:
        sys.exit(1)


async def run_sync() -> None:
    from agents.sync import SyncAgent

    agent = SyncAgent()
    await agent.poll_all_repos()


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python run_agent.py <agent_name>", file=sys.stderr)
        print("Available agents: refinement, sync", file=sys.stderr)
        sys.exit(1)

    agent_name = sys.argv[1]

    if agent_name == "refinement":
        await run_refinement()
    elif agent_name == "sync":
        await run_sync()
    else:
        print(f"Unknown agent: {agent_name}", file=sys.stderr)
        print("Available agents: refinement, sync", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
