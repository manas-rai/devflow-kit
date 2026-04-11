"""Jira tools — async wrappers around JiraClient for the SDK runner.

These functions are called by execute_tool() when the LLM wants to
interact with Jira. They delegate to JiraClient and return formatted
strings suitable for the agentic loop.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure project root on path so JiraClient can import core.models
sys.path.append(str(Path(__file__).parent.parent.parent))

from mcp_server.jira_client import JiraClient


def _make_client() -> JiraClient:
    """Instantiate JiraClient from environment variables at call time."""
    return JiraClient(
        base_url=os.environ.get("JIRA_BASE_URL", os.environ.get("JIRA_URL", "")),
        username=os.environ.get("JIRA_USER_EMAIL", os.environ.get("JIRA_USERNAME", "")),
        api_token=os.environ.get("JIRA_API_TOKEN", ""),
    )


async def read_jira_ticket(issue_key: str) -> str:
    """Return formatted ticket info as a string."""
    client = _make_client()
    try:
        work_item = await client.get_ticket(issue_key)
        lines = [
            f"Key: {work_item.key}",
            f"Title: {work_item.title}",
            f"Status: {work_item.status}",
            f"Type: {work_item.item_type}",
            f"URL: {work_item.url}",
            f"Description:\n{work_item.description or '(none)'}",
        ]
        if work_item.metadata:
            if work_item.metadata.get("priority"):
                lines.append(f"Priority: {work_item.metadata['priority']}")
            if work_item.metadata.get("labels"):
                lines.append(f"Labels: {', '.join(work_item.metadata['labels'])}")
            if work_item.metadata.get("acceptance_criteria"):
                lines.append(f"Acceptance Criteria:\n{work_item.metadata['acceptance_criteria']}")
            if work_item.metadata.get("comments"):
                comments = work_item.metadata["comments"]
                lines.append(f"Comments ({len(comments)}):")
                for c in comments[:5]:
                    lines.append(f"  [{c['author']}]: {c['body'][:200]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading Jira ticket {issue_key}: {e}"


async def update_jira_description(issue_key: str, refinement_summary: str) -> str:
    """Append a DevFlow refinement section to the ticket description."""
    client = _make_client()
    try:
        await client.update_description(issue_key, refinement_summary)
        return f"Successfully updated description for {issue_key}."
    except Exception as e:
        return f"Error updating description for {issue_key}: {e}"


async def update_jira_story_points(issue_key: str, story_points: float) -> str:
    """Update story points for a ticket."""
    client = _make_client()
    try:
        await client.update_story_points(issue_key, story_points)
        return f"Successfully updated story points for {issue_key} to {story_points}."
    except Exception as e:
        return f"Error updating story points for {issue_key}: {e}"


async def post_jira_comment(issue_key: str, comment: str) -> str:
    """Post a comment to a Jira ticket."""
    client = _make_client()
    try:
        await client.post_comment(issue_key, comment)
        return f"Successfully posted comment to {issue_key}."
    except Exception as e:
        return f"Error posting comment to {issue_key}: {e}"


async def transition_jira_ticket(issue_key: str, status: str) -> str:
    """Transition a Jira ticket to the given status."""
    client = _make_client()
    try:
        success = await client.transition_ticket(issue_key, status)
        if success:
            return f"Successfully transitioned {issue_key} to '{status}'."
        return f"Could not find transition to '{status}' for {issue_key}. Check available transitions."
    except Exception as e:
        return f"Error transitioning {issue_key} to '{status}': {e}"
