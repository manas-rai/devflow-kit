#!/usr/bin/env python3
"""Entry point for running agents from GitHub Actions workflows.

Usage:
    python run_agent.py refinement
    python run_agent.py implementation
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
        extra={
            "feedback": os.environ.get("FEEDBACK", ""),
            "github_issue_number": os.environ.get("GITHUB_ISSUE_NUMBER", ""),
            "event_type": os.environ.get("EVENT_TYPE", "devflow-refine"),
        },
    )

    agent = RefinementAgent()
    runner = AgentRunner()
    result = await runner.run(agent, context)

    _print_result(agent.name, result)

    if not result.succeeded:
        sys.exit(1)


async def run_implementation() -> None:
    from agents.implementation import ImplementationAgent

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
        extra={
            "github_issue_url": os.environ.get("GITHUB_ISSUE_URL", ""),
        },
    )

    agent = ImplementationAgent()
    runner = AgentRunner()
    result = await runner.run(agent, context)

    _print_result(agent.name, result)

    if not result.succeeded:
        sys.exit(1)


async def run_sync() -> None:
    from agents.sync import SyncAgent

    agent = SyncAgent()
    await agent.poll_all_repos()


def _print_result(agent_name: str, result) -> None:
    """Print agent execution summary."""
    print(f"\n{'='*60}")
    print(f"Agent: {agent_name}")
    print(f"Status: {result.status}")
    print(f"Attempts: {result.attempts}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Tool calls: {len(result.tool_calls)}")
    for tc in result.tool_calls:
        print(f"  - {tc.tool_name}")
    if result.error:
        print(f"Error: {result.error}")
    print("=" * 60)


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python run_agent.py <agent_name>", file=sys.stderr)
        print("Available agents: refinement, implementation, sync", file=sys.stderr)
        sys.exit(1)

    agent_name = sys.argv[1]

    # Print identification banner for CI logs
    issue_key = os.environ.get("ISSUE_KEY", "N/A")
    project_key = os.environ.get("PROJECT_KEY", "N/A")
    component = os.environ.get("COMPONENT", "N/A")
    event_type = os.environ.get("EVENT_TYPE", "N/A")
    repo, _ = resolve_target_repo() if agent_name != "sync" else ("all", "")

    print(f"\n{'='*50}", file=sys.stderr)
    print(f"  DevFlow Kit — {agent_name.upper()}", file=sys.stderr)
    print(f"  Ticket:  {issue_key} ({project_key}/{component})", file=sys.stderr)
    print(f"  Target:  {repo}", file=sys.stderr)
    print(f"  Event:   {event_type}", file=sys.stderr)
    print(f"{'='*50}\n", file=sys.stderr)

    if agent_name == "refinement":
        await run_refinement()
    elif agent_name == "implementation":
        await run_implementation()
    elif agent_name == "sync":
        await run_sync()
    else:
        print(f"Unknown agent: {agent_name}", file=sys.stderr)
        print("Available agents: refinement, implementation, sync", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
