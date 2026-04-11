"""GitHub tools — async wrappers around GitHubClient for the SDK runner.

These functions are called by execute_tool() when the LLM wants to
interact with GitHub. They delegate to GitHubClient and return formatted
strings suitable for the agentic loop.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root on path so GitHubClient can import properly
sys.path.append(str(Path(__file__).parent.parent.parent))

from mcp_server.github_client import GitHubClient


def _make_client() -> GitHubClient:
    """Instantiate GitHubClient from environment variables at call time."""
    return GitHubClient(token=os.environ.get("GH_PAT", os.environ.get("GITHUB_TOKEN", "")))


def _split_repo(repo: str) -> tuple[str, str]:
    """Split 'owner/name' into (owner, name)."""
    parts = repo.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid repo format {repo!r} — expected 'owner/name'")
    return parts[0], parts[1]


async def search_code(repo: str, query: str) -> str:
    """Search code in a repository and return formatted results."""
    client = _make_client()
    owner, name = _split_repo(repo)
    try:
        results = await client.search_code(owner, name, query)
        if not results:
            return f"No code results found for '{query}' in {repo}."
        lines = [f"Code search results for '{query}' in {repo}:"]
        for r in results:
            lines.append(f"  - {r['path']} ({r['url']})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching code in {repo}: {e}"


async def create_github_issue(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> str:
    """Create a GitHub issue and return its URL."""
    client = _make_client()
    owner, name = _split_repo(repo)
    try:
        issue = await client.create_issue(owner, name, title, body, labels)
        return f"Created GitHub issue #{issue.number}: {issue.url}"
    except Exception as e:
        return f"Error creating GitHub issue in {repo}: {e}"


async def update_github_issue(
    repo: str,
    issue_number: int,
    title: str | None = None,
    body: str | None = None,
) -> str:
    """Update an existing GitHub issue."""
    client = _make_client()
    owner, name = _split_repo(repo)
    try:
        issue = await client.update_issue(owner, name, issue_number, title=title, body=body)
        return f"Updated GitHub issue #{issue.number}: {issue.url}"
    except Exception as e:
        return f"Error updating GitHub issue #{issue_number} in {repo}: {e}"


async def post_github_comment(repo: str, issue_number: int, comment: str) -> str:
    """Post a comment on a GitHub issue."""
    client = _make_client()
    owner, name = _split_repo(repo)
    try:
        result = await client.comment_on_issue(owner, name, issue_number, comment)
        return f"Posted comment on #{issue_number}: {result.get('url', '')}"
    except Exception as e:
        return f"Error posting comment on #{issue_number} in {repo}: {e}"


async def create_branch(repo: str, branch_name: str, from_branch: str = "main") -> str:
    """Create a new branch from an existing one."""
    client = _make_client()
    owner, name = _split_repo(repo)
    try:
        ref = await client.create_branch(owner, name, branch_name, from_branch)
        return f"Created branch '{ref}' from '{from_branch}' in {repo}."
    except Exception as e:
        return f"Error creating branch '{branch_name}' in {repo}: {e}"


async def create_pull_request(
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
) -> str:
    """Create a pull request and return its URL."""
    client = _make_client()
    owner, name = _split_repo(repo)
    try:
        pr = await client.create_pull_request(owner, name, title, body, head, base)
        return f"Created PR #{pr['number']}: {pr['url']}"
    except Exception as e:
        return f"Error creating pull request in {repo}: {e}"
