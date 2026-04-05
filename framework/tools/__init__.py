"""Tool registry — maps tool names to async functions and ToolDef schemas.

Key exports:
- get_tools_for_agent(agent_name) -> list[ToolDef]
- execute_tool(tool_name, tool_input, context) -> str
"""
from __future__ import annotations

from typing import Any

from framework.providers.base import ToolDef

# ---------------------------------------------------------------------------
# ToolDef schemas — one entry per callable tool
# ---------------------------------------------------------------------------

_JIRA_TOOLS: list[ToolDef] = [
    ToolDef(
        name="read_jira_ticket",
        description="Read a Jira ticket and return its full details including description, status, and comments.",
        parameters={
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "The Jira issue key, e.g. PROJ-123"},
            },
            "required": ["issue_key"],
        },
    ),
    ToolDef(
        name="update_jira_description",
        description="Append a DevFlow refinement section to the Jira ticket description.",
        parameters={
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "The Jira issue key"},
                "refinement_summary": {"type": "string", "description": "The technical spec / refinement content to append"},
            },
            "required": ["issue_key", "refinement_summary"],
        },
    ),
    ToolDef(
        name="update_jira_story_points",
        description="Update the story point estimate on a Jira ticket.",
        parameters={
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "The Jira issue key"},
                "story_points": {"type": "number", "description": "Story point estimate (e.g. 3, 5, 8)"},
            },
            "required": ["issue_key", "story_points"],
        },
    ),
    ToolDef(
        name="post_jira_comment",
        description="Post a comment to a Jira ticket.",
        parameters={
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "The Jira issue key"},
                "comment": {"type": "string", "description": "The comment text to post"},
            },
            "required": ["issue_key", "comment"],
        },
    ),
    ToolDef(
        name="transition_jira_ticket",
        description="Transition a Jira ticket to a new status (e.g. 'In Progress', 'Done', 'Ready for Dev').",
        parameters={
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "The Jira issue key"},
                "status": {"type": "string", "description": "Target status name"},
            },
            "required": ["issue_key", "status"],
        },
    ),
]

_GITHUB_READ_TOOLS: list[ToolDef] = [
    ToolDef(
        name="search_code",
        description="Search for code in a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "GitHub repo in 'owner/name' format"},
                "query": {"type": "string", "description": "Search query string"},
            },
            "required": ["repo", "query"],
        },
    ),
]

_GITHUB_WRITE_TOOLS: list[ToolDef] = [
    ToolDef(
        name="create_github_issue",
        description="Create a GitHub issue and return its URL.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "GitHub repo in 'owner/name' format"},
                "title": {"type": "string", "description": "Issue title"},
                "body": {"type": "string", "description": "Issue body (markdown)"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of label names",
                },
            },
            "required": ["repo", "title", "body"],
        },
    ),
    ToolDef(
        name="update_github_issue",
        description="Update the title or body of an existing GitHub issue.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "GitHub repo in 'owner/name' format"},
                "issue_number": {"type": "integer", "description": "Issue number"},
                "title": {"type": "string", "description": "New title (optional)"},
                "body": {"type": "string", "description": "New body (optional)"},
            },
            "required": ["repo", "issue_number"],
        },
    ),
    ToolDef(
        name="post_github_comment",
        description="Post a comment on a GitHub issue or PR.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "GitHub repo in 'owner/name' format"},
                "issue_number": {"type": "integer", "description": "Issue or PR number"},
                "comment": {"type": "string", "description": "Comment text (markdown)"},
            },
            "required": ["repo", "issue_number", "comment"],
        },
    ),
    ToolDef(
        name="create_branch",
        description="Create a new branch in a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "GitHub repo in 'owner/name' format"},
                "branch_name": {"type": "string", "description": "Name of the new branch"},
                "from_branch": {"type": "string", "description": "Source branch (default: main)", "default": "main"},
            },
            "required": ["repo", "branch_name"],
        },
    ),
    ToolDef(
        name="create_pull_request",
        description="Create a pull request and return its URL.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "GitHub repo in 'owner/name' format"},
                "title": {"type": "string", "description": "PR title"},
                "body": {"type": "string", "description": "PR description (markdown)"},
                "head": {"type": "string", "description": "Head branch name"},
                "base": {"type": "string", "description": "Base branch (default: main)", "default": "main"},
            },
            "required": ["repo", "title", "body", "head"],
        },
    ),
]

_CODING_TOOLS: list[ToolDef] = [
    ToolDef(
        name="read_file",
        description="Read a file from the repository.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root"},
            },
            "required": ["path"],
        },
    ),
    ToolDef(
        name="write_file",
        description="Write content to a file in the repository (creates parent directories as needed).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root"},
                "content": {"type": "string", "description": "File content to write"},
            },
            "required": ["path", "content"],
        },
    ),
    ToolDef(
        name="list_files",
        description="List files in a directory within the repository.",
        parameters={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Directory path relative to repo root (default: '.')", "default": "."},
            },
            "required": [],
        },
    ),
    ToolDef(
        name="search_in_repo",
        description="Search for a text pattern in repository files matching a glob.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text pattern to search for"},
                "file_glob": {"type": "string", "description": "Glob pattern for files to search (default: '**/*.py')", "default": "**/*.py"},
            },
            "required": ["pattern"],
        },
    ),
    ToolDef(
        name="run_bash",
        description="Run a bash command in the repository root directory.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Bash command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 60)", "default": 60},
            },
            "required": ["command"],
        },
    ),
    ToolDef(
        name="git_status",
        description="Return git status of the repository.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    ToolDef(
        name="git_diff",
        description="Return git diff of staged and unstaged changes.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    ToolDef(
        name="git_add_and_commit",
        description="Stage all changes and create a git commit.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
            },
            "required": ["message"],
        },
    ),
    ToolDef(
        name="git_push",
        description="Push the current branch to origin.",
        parameters={
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch name to push"},
            },
            "required": ["branch"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Agent tool sets
# ---------------------------------------------------------------------------

_AGENT_TOOLS: dict[str, list[ToolDef]] = {
    # Refinement: Jira (read + write) + GitHub (read only)
    "refinement": _JIRA_TOOLS + _GITHUB_READ_TOOLS,
    # Implementation: all Jira + all GitHub write + coding tools
    "implementation": _JIRA_TOOLS + _GITHUB_READ_TOOLS + _GITHUB_WRITE_TOOLS + _CODING_TOOLS,
    # Decomposition: same as implementation
    "decomposition": _JIRA_TOOLS + _GITHUB_READ_TOOLS + _GITHUB_WRITE_TOOLS,
    # Verification: read tools only
    "verification": _JIRA_TOOLS + _GITHUB_READ_TOOLS,
}


def get_tools_for_agent(agent_name: str) -> list[ToolDef]:
    """Return tool definitions for the named agent.

    Falls back to all Jira + GitHub read tools for unknown agent names.
    """
    return _AGENT_TOOLS.get(agent_name, _JIRA_TOOLS + _GITHUB_READ_TOOLS)


# ---------------------------------------------------------------------------
# Tool dispatch — maps tool names to async callables
# ---------------------------------------------------------------------------

async def execute_tool(tool_name: str, tool_input: dict, context: Any) -> str:
    """Dispatch a tool call to the correct async function.

    Clients are instantiated at call time so env vars are read fresh.
    """
    from framework.tools.jira_tools import (
        read_jira_ticket,
        update_jira_description,
        update_jira_story_points,
        post_jira_comment,
        transition_jira_ticket,
    )
    from framework.tools.github_tools import (
        search_code,
        create_github_issue,
        update_github_issue,
        post_github_comment,
        create_branch,
        create_pull_request,
    )
    from framework.tools.coding_tools import (
        read_file,
        write_file,
        list_files,
        search_in_repo,
        run_bash,
        git_status,
        git_diff,
        git_add_and_commit,
        git_push,
    )

    dispatch = {
        # Jira
        "read_jira_ticket": lambda i: read_jira_ticket(**i),
        "update_jira_description": lambda i: update_jira_description(**i),
        "update_jira_story_points": lambda i: update_jira_story_points(**i),
        "post_jira_comment": lambda i: post_jira_comment(**i),
        "transition_jira_ticket": lambda i: transition_jira_ticket(**i),
        # GitHub
        "search_code": lambda i: search_code(**i),
        "create_github_issue": lambda i: create_github_issue(**i),
        "update_github_issue": lambda i: update_github_issue(**i),
        "post_github_comment": lambda i: post_github_comment(**i),
        "create_branch": lambda i: create_branch(**i),
        "create_pull_request": lambda i: create_pull_request(**i),
        # Coding
        "read_file": lambda i: read_file(**i),
        "write_file": lambda i: write_file(**i),
        "list_files": lambda i: list_files(**i),
        "search_in_repo": lambda i: search_in_repo(**i),
        "run_bash": lambda i: run_bash(**i),
        "git_status": lambda i: git_status(),
        "git_diff": lambda i: git_diff(),
        "git_add_and_commit": lambda i: git_add_and_commit(**i),
        "git_push": lambda i: git_push(**i),
    }

    handler = dispatch.get(tool_name)
    if handler is None:
        return f"Unknown tool: {tool_name!r}. Available tools: {sorted(dispatch.keys())}"

    try:
        return await handler(tool_input)
    except TypeError as e:
        return f"Tool {tool_name!r} called with invalid arguments: {e}"
    except Exception as e:
        return f"Tool {tool_name!r} failed: {e}"


__all__ = ["get_tools_for_agent", "execute_tool", "ToolDef"]
