#!/usr/bin/env python3
"""Entry point for running agents from GitHub Actions workflows.

Usage:
    python run_agent.py refinement
    python run_agent.py implementation
    python run_agent.py sync
    python run_agent.py verification
    python run_agent.py decomposition

This is pure wiring — reads env vars, creates context, picks the
agent, hands it to the runner. Zero decision logic.
"""

from __future__ import annotations

import asyncio
import os
import sys

from core.models import WorkItem, Spec
from framework.base_agent import AgentContext
from framework.runner import AgentRunner


def _generate_repo_map(target_repo: str, branch: str = "main") -> str:
    """Generate a structural repo map (zero LLM cost).

    Uses AST parsing to extract class/function signatures from the target
    repo. Returns a concise text map that gives the LLM a complete structural
    understanding of the codebase in ~2K tokens instead of ~150K.
    """
    import subprocess as _sp

    try:
        result = _sp.run(
            [
                sys.executable,
                "tools/repo_map.py",
                "--repo",
                target_repo,
                "--branch",
                branch,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            print(f"Repo map generated: {len(result.stdout)} chars", file=sys.stderr)
            return result.stdout.strip()
        print(f"Repo map generation failed: {result.stderr[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"Repo map generation error: {e}", file=sys.stderr)

    return "Repo map unavailable. Use search_code and get_file_content to explore."


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

    work_item = WorkItem(
        id=os.environ.get("ISSUE_KEY", ""),
        key=os.environ.get("ISSUE_KEY", ""),
        title=os.environ.get("SUMMARY", ""),
        description=os.environ.get("DESCRIPTION", ""),
        status="To Do",
        item_type="Story",
        url=f"{os.environ.get('JIRA_BASE_URL', '')}/browse/{os.environ.get('ISSUE_KEY', '')}"
    )

    # Generate repo map (zero LLM cost)
    repo_map = _generate_repo_map(repo, branch)

    context = AgentContext(
        issue_key=os.environ.get("ISSUE_KEY", ""),
        project_key=os.environ.get("PROJECT_KEY", ""),
        component=os.environ.get("COMPONENT", ""),
        summary=os.environ.get("SUMMARY", ""),
        description=os.environ.get("DESCRIPTION", ""),
        jira_base_url=os.environ.get("JIRA_BASE_URL", ""),
        target_repo=repo,
        target_branch=branch,
        work_item=work_item,
        extra={
            "feedback": os.environ.get("FEEDBACK", ""),
            "github_issue_number": os.environ.get("GITHUB_ISSUE_NUMBER", ""),
            "event_type": os.environ.get("EVENT_TYPE", "devflow-refine"),
            "repo_map": repo_map,
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

    work_item = WorkItem(
        id=os.environ.get("ISSUE_KEY", ""),
        key=os.environ.get("ISSUE_KEY", ""),
        title=os.environ.get("SUMMARY", ""),
        description=os.environ.get("DESCRIPTION", ""),
        status="Ready for Dev",
        item_type="Story",
        url=f"{os.environ.get('JIRA_BASE_URL', '')}/browse/{os.environ.get('ISSUE_KEY', '')}"
    )

    # Heuristic parsing to satisfy Spec object model
    desc = os.environ.get("DESCRIPTION", "")
    spec = Spec(
        work_item_key=os.environ.get("ISSUE_KEY", ""),
        summary=os.environ.get("SUMMARY", ""),
        goals=[line for line in desc.split("\n") if line.startswith("- ")][:3],
        acceptance_criteria=[line for line in desc.split("\n") if line.startswith("- [ ]")]
    )

    # Generate repo map (zero LLM cost)
    repo_map = _generate_repo_map(repo, branch)

    context = AgentContext(
        issue_key=os.environ.get("ISSUE_KEY", ""),
        project_key=os.environ.get("PROJECT_KEY", ""),
        component=os.environ.get("COMPONENT", ""),
        summary=os.environ.get("SUMMARY", ""),
        description=desc,
        jira_base_url=os.environ.get("JIRA_BASE_URL", ""),
        target_repo=repo,
        target_branch=branch,
        work_item=work_item,
        spec=spec,
        extra={
            "github_issue_url": os.environ.get("GITHUB_ISSUE_URL", ""),
            "repo_map": repo_map,
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


async def run_verification() -> None:
    from agents.verification import VerificationAgent

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
            "github_pr_url": os.environ.get("GITHUB_PR_URL", ""),
            "event_type": os.environ.get("EVENT_TYPE", "devflow-verify"),
        },
    )

    agent = VerificationAgent()
    runner = AgentRunner()
    result = await runner.run(agent, context)

    _print_result(agent.name, result)

    if not result.succeeded:
        sys.exit(1)


async def run_decomposition() -> None:
    from agents.decomposition import DecompositionAgent

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
            "event_type": os.environ.get("EVENT_TYPE", "devflow-decompose"),
        },
    )

    agent = DecompositionAgent()
    runner = AgentRunner()
    result = await runner.run(agent, context)

    _print_result(agent.name, result)

    if not result.succeeded:
        sys.exit(1)


def _print_result(agent_name: str, result) -> None:
    """Print agent execution summary."""
    print(f"\n{'='*60}")
    print(f"Agent: {agent_name}")
    print(f"Status: {result.status}")
    print(f"Attempts: {result.attempts}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    if result.input_tokens or result.output_tokens:
        print(f"Tokens: {result.input_tokens:,} input / {result.output_tokens:,} output")
    print(f"Tool calls: {len(result.tool_calls)}")
    for tc in result.tool_calls:
        token_info = f" ({tc.input_tokens:,} in / {tc.output_tokens:,} out)" if tc.input_tokens or tc.output_tokens else ""
        print(f"  - {tc.tool_name}{token_info}")
    if result.error:
        print(f"Error: {result.error}")
    print("=" * 60)


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python run_agent.py <agent_name>", file=sys.stderr)
        print("Available agents: refinement, implementation, sync, verification, decomposition", file=sys.stderr)
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
    elif agent_name == "verification":
        await run_verification()
    elif agent_name == "decomposition":
        await run_decomposition()
    else:
        print(f"Unknown agent: {agent_name}", file=sys.stderr)
        print("Available agents: refinement, implementation, sync, verification, decomposition", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
