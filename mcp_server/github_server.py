"""DevFlow GitHub MCP Server — GitHub integration via FastMCP.

Resources:
    github://repo/{owner}/{name}              — Repo structure + README + CLAUDE.md
    github://repo/{owner}/{name}/file/{path}  — Single file content
    github://issue/{owner}/{name}/{number}    — GitHub issue (technical spec)

Tools:
    create_technical_issue  — Create GitHub issue with technical spec
    update_technical_issue  — Update existing issue
    post_github_comment    — Comment on an issue (e.g. @claude trigger)
    create_branch           — Create branch in target repo
    create_pull_request     — Create PR for changes
    search_code             — Search code in target repo
"""

from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from github_client import GitHubClient

mcp = FastMCP("devflow-github")
github = GitHubClient()


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("github://repo/{owner}/{name}")
async def get_repo_structure(owner: str, name: str) -> str:
    """Read repo structure: file tree, README, and CLAUDE.md."""
    structure = await github.get_repo_structure(owner, name)

    parts = [f"# {structure.owner}/{structure.name}\n"]
    parts.append(f"**Default branch**: {structure.default_branch}\n")

    if structure.claude_md:
        parts.append(f"## CLAUDE.md\n{structure.claude_md[:2000]}\n")

    if structure.readme:
        parts.append(f"## README.md\n{structure.readme[:3000]}\n")

    if structure.file_tree:
        parts.append(f"## File Tree ({len(structure.file_tree)} entries)")
        parts.append("\n".join(structure.file_tree[:100]))

    return "\n".join(parts)


@mcp.resource("github://repo/{owner}/{name}/file/{path}")
async def get_file_content(owner: str, name: str, path: str) -> str:
    """Read a single file from a GitHub repository."""
    content = await github.get_file_content(owner, name, path)
    if not content:
        return f"File not found: {path}"
    return content


@mcp.resource("github://issue/{owner}/{name}/{number}")
async def get_github_issue(owner: str, name: str, number: int) -> str:
    """Read a GitHub issue (technical spec created by refinement)."""
    issue = await github.get_issue(owner, name, number)
    parts = [
        f"# #{issue.number}: {issue.title}\n",
        f"**State**: {issue.state}",
        f"**URL**: {issue.url}",
    ]
    if issue.labels:
        parts.append(f"**Labels**: {', '.join(issue.labels)}")
    parts.append(f"\n## Body\n{issue.body}")
    return "\n".join(parts)


@mcp.resource("devflow://repo-map")
def get_repo_map() -> str:
    """Read the repo routing config: Jira project/component → GitHub repo."""
    repo_map_path = os.path.join(os.path.dirname(__file__), "..", "repo-map.json")
    with open(repo_map_path) as f:
        return json.dumps(json.load(f), indent=2)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def create_technical_issue(
    owner: str,
    repo: str,
    title: str,
    body: str,
    jira_key: str = "",
) -> str:
    """Create a GitHub issue with a technical spec.

    Args:
        owner: GitHub repo owner (e.g. "manas-rai")
        repo: GitHub repo name (e.g. "cloud-waste-hunter")
        title: Issue title — should include Jira key like "[CWH-38] Add detection"
        body: Full technical spec in markdown (files to change, approach, AC)
        jira_key: Linked Jira ticket key for cross-reference (optional)
    """
    full_body = body
    if jira_key:
        full_body += f"\n\n---\n🔗 Jira: {jira_key}"

    issue = await github.create_issue(
        owner=owner,
        name=repo,
        title=title,
        body=full_body,
        labels=["devflow-kit", "ai-implementation"],
    )
    return f"✅ Created issue #{issue.number}: {issue.url}"


@mcp.tool()
async def update_technical_issue(
    owner: str,
    repo: str,
    issue_number: int,
    body: str,
    title: str | None = None,
) -> str:
    """Update an existing GitHub issue.

    Args:
        owner: GitHub repo owner
        repo: GitHub repo name
        issue_number: Issue number to update
        body: Updated body
        title: Updated title (optional)
    """
    issue = await github.update_issue(
        owner=owner,
        name=repo,
        number=issue_number,
        title=title,
        body=body,
    )
    return f"✅ Updated issue #{issue.number}: {issue.url}"


@mcp.tool()
async def post_github_comment(
    owner: str,
    repo: str,
    issue_number: int,
    comment: str,
) -> str:
    """Post a comment on a GitHub issue.

    Use this to trigger Claude Code via @claude or to add context.

    Args:
        owner: GitHub repo owner
        repo: GitHub repo name
        issue_number: Issue number to comment on
        comment: Comment body text
    """
    result = await github.comment_on_issue(
        owner=owner,
        name=repo,
        number=issue_number,
        body=comment,
    )
    return f"✅ Posted comment on #{issue_number}: {result['url']}"


@mcp.tool()
async def create_branch(
    owner: str,
    repo: str,
    branch_name: str,
    from_branch: str = "main",
) -> str:
    """Create a new branch in the target repo for implementation.

    Args:
        owner: GitHub repo owner
        repo: GitHub repo name
        branch_name: New branch name (e.g. "CWH-38/add-snapshot-detection")
        from_branch: Source branch to branch from (default: "main")
    """
    branch = await github.create_branch(
        owner=owner,
        name=repo,
        branch_name=branch_name,
        from_branch=from_branch,
    )
    return f"✅ Created branch: {branch}"


@mcp.tool()
async def create_pull_request(
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
) -> str:
    """Create a pull request for implemented changes.

    Args:
        owner: GitHub repo owner
        repo: GitHub repo name
        title: PR title (should reference Jira key)
        body: PR description (link to Jira ticket + GitHub issue)
        head: Head/feature branch name
        base: Base branch to merge into (default: "main")
    """
    pr = await github.create_pull_request(
        owner=owner,
        name=repo,
        title=title,
        body=body,
        head=head,
        base=base,
        labels=["devflow-kit", "ai-implementation"],
    )
    return f"✅ Created PR #{pr['number']}: {pr['url']}"


@mcp.tool()
async def search_code(
    owner: str,
    repo: str,
    query: str,
) -> str:
    """Search code in a repository to understand the codebase.

    Args:
        owner: GitHub repo owner
        repo: GitHub repo name
        query: Search query (e.g. "def create_issue" or "class UserService")
    """
    results = await github.search_code(owner=owner, name=repo, query=query)
    if not results:
        return "No results found."
    lines = [f"Found {len(results)} results:\n"]
    for r in results:
        lines.append(f"- `{r['path']}` — {r['name']}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
