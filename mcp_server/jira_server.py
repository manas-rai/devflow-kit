"""DevFlow Jira MCP Server — Jira integration via FastMCP.

Resources:
    jira://ticket/{key}           — Business ticket details
    jira://ticket/{key}/comments  — Ticket comments (for re-refinement)

Tools:
    post_jira_comment      — Post a comment to Jira
    transition_jira_ticket — Move ticket status
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from jira_client import JiraClient

mcp = FastMCP("devflow-jira")
jira = JiraClient()


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("jira://ticket/{key}")
async def get_ticket(key: str) -> str:
    """Read a Jira ticket with business-level details: summary, description, AC, priority."""
    ticket = await jira.get_ticket(key)
    parts = [
        f"# {ticket.key}: {ticket.summary}\n",
        f"**Status**: {ticket.status}",
        f"**Priority**: {ticket.priority}",
        f"**Type**: {ticket.issue_type}",
    ]
    if ticket.labels:
        parts.append(f"**Labels**: {', '.join(ticket.labels)}")
    if ticket.components:
        parts.append(f"**Components**: {', '.join(ticket.components)}")
    if ticket.parent_key:
        parts.append(f"**Parent**: {ticket.parent_key}")

    parts.append(f"\n## Description\n{ticket.description}")

    if ticket.acceptance_criteria:
        parts.append(f"\n## Acceptance Criteria\n{ticket.acceptance_criteria}")

    if ticket.comments:
        parts.append(f"\n## Recent Comments ({len(ticket.comments)})")
        for c in ticket.comments[-5:]:
            parts.append(f"\n**{c['author']}** ({c['created']}):\n{c['body']}")

    return "\n".join(parts)


@mcp.resource("jira://ticket/{key}/comments")
async def get_ticket_comments(key: str) -> str:
    """Read all comments on a Jira ticket (useful for PM feedback in re-refinement)."""
    comments = await jira.get_comments(key)
    if not comments:
        return f"No comments on {key}"

    lines = [f"## Comments on {key}\n"]
    for c in comments:
        lines.append(f"**{c['author']}** ({c['created']}):\n{c['body']}\n---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def post_jira_comment(issue_key: str, comment: str) -> str:
    """Post a comment to a Jira ticket to update the team.

    Args:
        issue_key: Jira issue key (e.g. CWH-38)
        comment: Comment text to post
    """
    await jira.post_comment(issue_key, comment)
    return f"✅ Posted comment to {issue_key}"


@mcp.tool()
async def update_jira_description(issue_key: str, refinement_summary: str) -> str:
    """Update the Jira ticket description with the refinement summary.

    This APPENDS a "DevFlow Refinement" section to the existing description,
    preserving the original business content written by the PM.

    Args:
        issue_key: Jira issue key (e.g. CWH-38)
        refinement_summary: The refinement summary to append (approach, GitHub issue link, key findings)
    """
    await jira.update_description(issue_key, refinement_summary)
    return f"✅ Updated description of {issue_key}"


@mcp.tool()
async def update_jira_story_points(issue_key: str, points: float) -> str:
    """Update the story points estimate for a Jira ticket.

    Args:
        issue_key: Jira issue key (e.g. CWH-38)
        points: The story point value to set (e.g. 1, 2, 3, 5, 8)
    """
    await jira.update_story_points(issue_key, points)
    return f"✅ Updated story points for {issue_key} to {points}"


@mcp.tool()
async def transition_jira_ticket(issue_key: str, status: str) -> str:
    """Move a Jira ticket to a new status.

    IMPORTANT: The refinement agent should NOT use this tool.
    Only the implementation agent should transition tickets.

    Args:
        issue_key: Jira issue key (e.g. CWH-38)
        status: Target status name (e.g. "In Progress", "Done")
    """
    success = await jira.transition_ticket(issue_key, status)
    if success:
        return f"✅ Transitioned {issue_key} → {status}"
    return f"⚠️ Could not transition {issue_key} — status '{status}' not available"


if __name__ == "__main__":
    mcp.run()
