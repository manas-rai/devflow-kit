"""Jira REST API client for the DevFlow MCP server.

Provides typed methods for all Jira operations needed by DevFlow Kit:
- Reading tickets (summary, description, AC, comments)
- Posting comments (ADF format)
- Transitioning ticket status
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx

# Add project root to path so we can import core
sys.path.append(str(Path(__file__).parent.parent))

from core.models import WorkItem


class JiraClient:
    """Typed Jira REST API client."""

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        api_token: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("JIRA_URL", "")).rstrip("/")
        self.username = username or os.environ.get("JIRA_USERNAME", "")
        self.api_token = api_token or os.environ.get("JIRA_API_TOKEN", "")
        self._auth = (self.username, self.api_token)
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def get_ticket(self, key: str) -> WorkItem:
        """Fetch a Jira ticket with all business-relevant fields."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/rest/api/3/issue/{key}",
                auth=self._auth,
                headers=self._headers,
                params={
                    "fields": "summary,description,status,priority,issuetype,"
                    "labels,components,comment,parent,subtasks"
                },
            )
            resp.raise_for_status()
            data = resp.json()

        fields = data.get("fields", {})

        # Parse description from ADF to plain text
        description = self._adf_to_text(fields.get("description"))

        # Extract acceptance criteria from description
        ac = self._extract_acceptance_criteria(description)

        # Parse comments
        comments = []
        for c in fields.get("comment", {}).get("comments", []):
            comments.append(
                {
                    "author": c.get("author", {}).get("displayName", "Unknown"),
                    "body": self._adf_to_text(c.get("body")),
                    "created": c.get("created", ""),
                }
            )

        # Parse components
        components = [c.get("name", "") for c in fields.get("components", [])]

        # Parse subtasks
        subtasks = [s["key"] for s in fields.get("subtasks", [])]

        # Parse parent
        parent = fields.get("parent", {})
        parent_key = parent.get("key", "") if parent else ""

        return WorkItem(
            id=data.get("id", ""),
            key=key,
            title=fields.get("summary", ""),
            description=description,
            status=fields.get("status", {}).get("name", ""),
            item_type=fields.get("issuetype", {}).get("name", ""),
            url=f"{self.base_url}/browse/{key}",
            metadata={
                "priority": fields.get("priority", {}).get("name", ""),
                "labels": fields.get("labels", []),
                "components": components,
                "acceptance_criteria": ac,
                "comments": comments,
                "parent_key": parent_key,
                "subtask_keys": subtasks,
            },
        )

    async def get_comments(self, key: str) -> list[dict[str, str]]:
        """Fetch all comments for a ticket."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/rest/api/3/issue/{key}/comment",
                auth=self._auth,
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()

        comments = []
        for c in data.get("comments", []):
            comments.append(
                {
                    "author": c.get("author", {}).get("displayName", "Unknown"),
                    "body": self._adf_to_text(c.get("body")),
                    "created": c.get("created", ""),
                }
            )
        return comments

    async def post_comment(self, key: str, text: str) -> None:
        """Post an ADF-formatted comment to a ticket."""
        payload = {
            "body": {
                "version": 1,
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": text}],
                    }
                ],
            }
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/rest/api/3/issue/{key}/comment",
                auth=self._auth,
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()

    async def update_description(self, key: str, description: str) -> None:
        """Update the description field of a Jira ticket.

        Appends a DevFlow refinement section to the existing description,
        preserving the original business content. Parses markdown-style
        headings and lists into proper ADF for Jira rendering.
        """
        # First, get the existing description
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/rest/api/3/issue/{key}",
                auth=self._auth,
                headers=self._headers,
                params={"fields": "description"},
            )
            resp.raise_for_status()
            existing = resp.json().get("fields", {}).get("description")

        # Build new description: existing + devflow section
        content_blocks: list[dict] = []

        # Preserve existing description content
        if existing and isinstance(existing, dict):
            content_blocks.extend(existing.get("content", []))

        # Add separator
        content_blocks.append({"type": "rule"})

        # Add DevFlow refinement heading
        content_blocks.append(
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "🤖 DevFlow Refinement"}],
            }
        )

        # Parse the markdown-style description into ADF blocks
        content_blocks.extend(self._markdown_to_adf(description))

        payload = {
            "fields": {
                "description": {
                    "version": 1,
                    "type": "doc",
                    "content": content_blocks,
                }
            }
        }

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{self.base_url}/rest/api/3/issue/{key}",
                auth=self._auth,
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()

    async def get_story_points_field_id(self) -> str:
        """Dynamically find the custom field ID for Story Points."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/rest/api/3/field",
                auth=self._auth,
                headers=self._headers,
            )
            resp.raise_for_status()
            fields = resp.json()

        for f in fields:
            name = f.get("name", "").lower()
            if name in ["story point estimate", "story points"]:
                return f["id"]

        raise ValueError("Could not find Story Points field in Jira instance")

    async def update_story_points(self, key: str, points: float) -> None:
        """Update the story points for a ticket."""
        if not hasattr(self, "_story_points_field_id"):
            self._story_points_field_id = await self.get_story_points_field_id()

        payload = {"fields": {self._story_points_field_id: points}}

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{self.base_url}/rest/api/3/issue/{key}",
                auth=self._auth,
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()

    @staticmethod
    def _markdown_to_adf(text: str) -> list[dict[str, Any]]:
        """Convert markdown-style text to ADF blocks.

        Supports:
        - ## Heading → ADF heading level 3 (bold, larger)
        - - item → bullet list
        - - [ ] item → task list (checkbox)
        - Plain text → paragraph
        """
        import uuid

        # Handle cases where the LLM or JSON parsing results in literal \n characters
        text = text.replace("\\n", "\n")

        blocks: list[dict] = []
        lines = text.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                i += 1
                continue

            if stripped.startswith("## "):
                blocks.append(
                    {
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": [
                            {
                                "type": "text",
                                "text": stripped[3:].strip() or " ",
                            }
                        ],
                    }
                )
                i += 1
                continue

            if stripped.startswith("### "):
                blocks.append(
                    {
                        "type": "heading",
                        "attrs": {"level": 4},
                        "content": [
                            {
                                "type": "text",
                                "text": stripped[4:].strip() or " ",
                            }
                        ],
                    }
                )
                i += 1
                continue

            # Task list (- [ ] item)
            if stripped.startswith("- [ ] ") or stripped.startswith("- [x] "):
                task_items: list[dict] = []
                while i < len(lines):
                    s = lines[i].strip()
                    if s.startswith("- [ ] "):
                        task_items.append(
                            {
                                "type": "taskItem",
                                "attrs": {"state": "TODO", "localId": str(uuid.uuid4())},
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": s[6:].strip(),
                                            }
                                        ],
                                    }
                                ],
                            }
                        )
                        i += 1
                    elif s.startswith("- [x] "):
                        task_items.append(
                            {
                                "type": "taskItem",
                                "attrs": {"state": "DONE", "localId": str(uuid.uuid4())},
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": s[6:].strip() or " ",
                                            }
                                        ],
                                    }
                                ],
                            }
                        )
                        i += 1
                    else:
                        break
                blocks.append(
                    {
                        "type": "taskList",
                        "attrs": {"localId": str(uuid.uuid4())},
                        "content": task_items,
                    }
                )
                continue

            # Bullet list (- item)
            if stripped.startswith("- "):
                list_items: list[dict] = []
                while i < len(lines):
                    s = lines[i].strip()
                    is_bullet = (
                        s.startswith("- ")
                        and not s.startswith("- [ ]")
                        and not s.startswith("- [x]")
                    )
                    if is_bullet:
                        list_items.append(
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": s[2:].strip() or " ",
                                            }
                                        ],
                                    }
                                ],
                            }
                        )
                        i += 1
                    else:
                        break
                blocks.append(
                    {
                        "type": "bulletList",
                        "content": list_items,
                    }
                )
                continue

            # Plain text → paragraph
            blocks.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": stripped or " "}],
                }
            )
            i += 1

        return blocks

    async def transition_ticket(self, key: str, target_status: str) -> bool:
        """Transition a ticket to a new status. Returns True if successful."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/rest/api/3/issue/{key}/transitions",
                auth=self._auth,
                headers=self._headers,
            )
            resp.raise_for_status()
            transitions = resp.json().get("transitions", [])

            target = next(
                (t for t in transitions if t["name"].lower() == target_status.lower()),
                None,
            )
            if not target:
                return False

            resp = await client.post(
                f"{self.base_url}/rest/api/3/issue/{key}/transitions",
                auth=self._auth,
                headers=self._headers,
                json={"transition": {"id": target["id"]}},
            )
            resp.raise_for_status()
            return True

    @staticmethod
    def _adf_to_text(adf: Any) -> str:
        """Convert Atlassian Document Format to plain text."""
        if not adf or not isinstance(adf, dict):
            return ""

        lines: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, str):
                lines.append(node)
                return
            if not isinstance(node, dict):
                return

            node_type = node.get("type", "")

            # Handle text nodes
            if node_type == "text":
                lines.append(node.get("text", ""))
                return

            # Handle headings
            if node_type == "heading":
                level = node.get("attrs", {}).get("level", 1)
                lines.append("\n" + "#" * level + " ")

            # Handle list items
            if node_type == "listItem":
                lines.append("\n- ")

            # Handle paragraphs
            if node_type == "paragraph" and lines and lines[-1] != "\n":
                lines.append("\n")

            # Recurse into children
            for child in node.get("content", []):
                walk(child)

            if node_type in ("paragraph", "heading"):
                lines.append("\n")

        walk(adf)
        return "".join(lines).strip()

    @staticmethod
    def _extract_acceptance_criteria(description: str) -> str:
        """Extract Acceptance Criteria section from description."""
        lines = description.split("\n")
        in_ac = False
        ac_lines: list[str] = []

        for line in lines:
            lower = line.lower().strip()
            if "acceptance criteria" in lower:
                in_ac = True
                continue
            if in_ac:
                # Stop at next heading
                if lower.startswith("#") and "acceptance" not in lower:
                    break
                ac_lines.append(line)

        return "\n".join(ac_lines).strip()
