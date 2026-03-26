"""GitHub REST API client for the DevFlow MCP server.

Provides typed methods for all GitHub operations needed by DevFlow Kit:
- Reading repo structure, files, issues
- Creating/commenting on issues, branches, PRs
- Searching code
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field

import httpx

API_BASE = "https://api.github.com"


@dataclass
class RepoStructure:
    """Parsed repository structure."""

    owner: str
    name: str
    default_branch: str
    readme: str = ""
    claude_md: str = ""
    file_tree: list[str] = field(default_factory=list)


@dataclass
class GitHubIssue:
    """Parsed GitHub issue."""

    number: int
    title: str
    body: str
    state: str
    labels: list[str] = field(default_factory=list)
    url: str = ""


class GitHubClient:
    """Typed GitHub REST API client."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_repo_structure(
        self, owner: str, name: str, branch: str = "main"
    ) -> RepoStructure:
        """Fetch repo structure: README, CLAUDE.md, and file tree."""
        async with httpx.AsyncClient() as client:
            # Get default branch
            repo_resp = await client.get(
                f"{API_BASE}/repos/{owner}/{name}",
                headers=self._headers,
            )
            repo_resp.raise_for_status()
            default_branch = repo_resp.json().get("default_branch", branch)

            # Get file tree (recursive, truncated to top 2 levels)
            tree_resp = await client.get(
                f"{API_BASE}/repos/{owner}/{name}/git/trees/{default_branch}",
                headers=self._headers,
                params={"recursive": "1"},
            )
            tree_resp.raise_for_status()
            tree_data = tree_resp.json()

            file_tree = []
            for item in tree_data.get("tree", []):
                path = item["path"]
                # Limit depth to keep it manageable
                if path.count("/") <= 2:
                    prefix = "📁 " if item["type"] == "tree" else "📄 "
                    file_tree.append(f"{prefix}{path}")

            # Try to read README.md
            readme = await self._get_file_content(client, owner, name, "README.md", default_branch)

            # Try to read CLAUDE.md
            claude_md = await self._get_file_content(client, owner, name, "CLAUDE.md", default_branch)

        return RepoStructure(
            owner=owner,
            name=name,
            default_branch=default_branch,
            readme=readme,
            claude_md=claude_md,
            file_tree=file_tree,
        )

    async def get_file_content(
        self, owner: str, name: str, path: str, ref: str = "main"
    ) -> str:
        """Fetch a single file's content from a repo."""
        async with httpx.AsyncClient() as client:
            return await self._get_file_content(client, owner, name, path, ref)

    async def _get_file_content(
        self,
        client: httpx.AsyncClient,
        owner: str,
        name: str,
        path: str,
        ref: str,
    ) -> str:
        """Internal: fetch file content, return empty string on 404."""
        try:
            resp = await client.get(
                f"{API_BASE}/repos/{owner}/{name}/contents/{path}",
                headers=self._headers,
                params={"ref": ref},
            )
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", "")
            if content:
                return base64.b64decode(content).decode("utf-8", errors="replace")
            return ""
        except Exception:
            return ""

    async def get_issue(self, owner: str, name: str, number: int) -> GitHubIssue:
        """Fetch a GitHub issue."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{API_BASE}/repos/{owner}/{name}/issues/{number}",
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()

        return GitHubIssue(
            number=data["number"],
            title=data.get("title", ""),
            body=data.get("body", ""),
            state=data.get("state", ""),
            labels=[l["name"] for l in data.get("labels", [])],
            url=data.get("html_url", ""),
        )

    async def create_issue(
        self,
        owner: str,
        name: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> GitHubIssue:
        """Create a GitHub issue and return it."""
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE}/repos/{owner}/{name}/issues",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return GitHubIssue(
            number=data["number"],
            title=data.get("title", ""),
            body=data.get("body", ""),
            state=data.get("state", ""),
            labels=[l["name"] for l in data.get("labels", [])],
            url=data.get("html_url", ""),
        )

    async def comment_on_issue(
        self, owner: str, name: str, number: int, body: str
    ) -> dict:
        """Post a comment on a GitHub issue."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE}/repos/{owner}/{name}/issues/{number}/comments",
                headers=self._headers,
                json={"body": body},
            )
            resp.raise_for_status()
            data = resp.json()

        return {
            "id": data["id"],
            "url": data.get("html_url", ""),
            "body": data.get("body", ""),
        }

    async def update_issue(
        self,
        owner: str,
        name: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        labels: list[str] | None = None,
    ) -> GitHubIssue:
        """Update an existing GitHub issue."""
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if labels is not None:
            payload["labels"] = labels

        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{API_BASE}/repos/{owner}/{name}/issues/{number}",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return GitHubIssue(
            number=data["number"],
            title=data.get("title", ""),
            body=data.get("body", ""),
            state=data.get("state", ""),
            labels=[l["name"] for l in data.get("labels", [])],
            url=data.get("html_url", ""),
        )

    async def create_branch(
        self, owner: str, name: str, branch_name: str, from_branch: str = "main"
    ) -> str:
        """Create a new branch from an existing one. Returns the new branch ref."""
        async with httpx.AsyncClient() as client:
            # Get SHA of source branch
            resp = await client.get(
                f"{API_BASE}/repos/{owner}/{name}/git/ref/heads/{from_branch}",
                headers=self._headers,
            )
            resp.raise_for_status()
            sha = resp.json()["object"]["sha"]

            # Create new branch
            resp = await client.post(
                f"{API_BASE}/repos/{owner}/{name}/git/refs",
                headers=self._headers,
                json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            )
            resp.raise_for_status()

        return branch_name

    async def create_pull_request(
        self,
        owner: str,
        name: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        labels: list[str] | None = None,
    ) -> dict:
        """Create a pull request."""
        payload = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE}/repos/{owner}/{name}/pulls",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            pr_data = resp.json()

            # Add labels if provided
            if labels:
                await client.post(
                    f"{API_BASE}/repos/{owner}/{name}/issues/{pr_data['number']}/labels",
                    headers=self._headers,
                    json={"labels": labels},
                )

        return {
            "number": pr_data["number"],
            "url": pr_data["html_url"],
            "title": pr_data["title"],
        }

    async def search_code(
        self, owner: str, name: str, query: str, max_results: int = 10
    ) -> list[dict[str, str]]:
        """Search code in a repository."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{API_BASE}/search/code",
                headers=self._headers,
                params={"q": f"{query} repo:{owner}/{name}", "per_page": max_results},
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("items", [])[:max_results]:
            results.append({
                "path": item.get("path", ""),
                "url": item.get("html_url", ""),
                "name": item.get("name", ""),
            })
        return results
