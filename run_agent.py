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


def _get_runner(agent):
    """Return the correct runner based on LLM_PROVIDER env var or agent config."""
    provider = os.environ.get("LLM_PROVIDER", getattr(agent, "provider", "cli"))
    if provider == "cli":
        return AgentRunner()
    else:
        from framework.sdk_runner import SDKRunner
        model = os.environ.get("LLM_MODEL", getattr(agent, "model", None))
        return SDKRunner(provider=provider, model=model)


def _fetch_graph_report(target_repo: str, branch: str = "main") -> str | None:
    """Fetch the stored Graphify GRAPH_REPORT.md for a repo, or None.

    Reads the knowledge graph built by the graphify-onboard / graphify-sync
    workflows from object storage. Best-effort: any failure (missing graph,
    no storage config, network error) returns None so the caller falls back
    to the AST map. Never raises.
    """
    try:
        from tools.graph_store import GraphStore

        store = GraphStore()
        report = store.read_report(target_repo)
        if not report:
            print(f"No stored graph for {target_repo}", file=sys.stderr)
            return None

        meta = store.get_repo_meta(target_repo)
        as_of = ""
        if meta and meta.last_sha:
            as_of = f" (graph as of {meta.last_sha[:8]}, updated {meta.updated_at})"
        header = (
            f"# Code Knowledge Graph — {target_repo}{as_of}\n"
            "Built with Graphify. Community Hubs are logical components; "
            "God Nodes are highly-connected hotspots.\n\n"
        )
        print(f"Using Graphify graph for {target_repo}{as_of}", file=sys.stderr)
        return header + report
    except Exception as e:
        print(f"Graph fetch failed for {target_repo}: {e}", file=sys.stderr)
        return None


def _generate_repo_map(target_repo: str, branch: str = "main", compact: bool = False) -> str:
    """Return a structural understanding of the target repo for the prompt.

    Engine is selected by the ``REPO_MAP_ENGINE`` env var:
      - ``graphify`` → the stored Graphify knowledge graph (rich, multi-language),
        falling back to the AST map if no graph is available.
      - ``ast`` (default) → AST parsing to extract class/function signatures,
        giving a complete structural map in ~2K tokens instead of ~150K.

    Args:
        compact: If True, generates a minimal AST map with only top-level
                 class/function names (no methods/signatures/docstrings).
                 Ignored by the graphify engine (the report is already concise).
    """
    if os.environ.get("REPO_MAP_ENGINE", "ast").lower() == "graphify":
        report = _fetch_graph_report(target_repo, branch)
        if report:
            return report
        print("Falling back to AST repo map", file=sys.stderr)

    import subprocess as _sp

    try:
        cmd = [
            sys.executable,
            "tools/repo_map.py",
            "--repo",
            target_repo,
            "--branch",
            branch,
        ]
        if compact:
            cmd.append("--compact")
        result = _sp.run(
            cmd,
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
    """Read repo-map.json and resolve the target repo from env vars.
    Injects LLM_PROVIDER and LLM_MODEL into os.environ if specified.
    """
    import subprocess
    import json

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
    
    if result.returncode != 0:
        return ("", "main")
        
    try:
        data = json.loads(result.stdout.strip())
        
        # Override global provider with route-specific provider if configured
        if data.get("llm_provider"):
            os.environ["LLM_PROVIDER"] = data["llm_provider"]
        if data.get("llm_model"):
            os.environ["LLM_MODEL"] = data["llm_model"]
            
        return (data.get("github_repo", ""), data.get("branch", "main"))
    except json.JSONDecodeError:
        return ("", "main")


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

    # Generate compact repo map for refinement (top-level only, ~4x smaller)
    repo_map = _generate_repo_map(repo, branch, compact=True)

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
    runner = _get_runner(agent)
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
    runner = _get_runner(agent)
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
