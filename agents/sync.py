"""SyncAgent — keeps Jira in sync with GitHub PR lifecycle.

This agent is deterministic — no Claude Code involved.
It polls target repos for PR activity and updates Jira accordingly.

It also tracks decomposed ticket completion: when all subtasks' PRs
are merged, it transitions the parent ticket to Done.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys

import httpx


def extract_jira_key(text: str) -> str | None:
    """Extract a Jira issue key (e.g., PROJ-123) from text."""
    match = re.search(r"[A-Z][A-Z0-9]+-\d+", text)
    return match.group(0) if match else None


class SyncAgent:
    """Polls tracked repos for PR activity and syncs to Jira.

    Uses PR labels to track sync state (stateless — no database):
      - 'devflow-kit'           → created by DevFlow Kit
      - 'devflow-synced-opened' → Jira notified of PR open
      - 'devflow-synced-merged' → Jira notified of merge
    """

    def __init__(self) -> None:
        self.pat = os.environ["GITHUB_PAT"]
        self.jira_base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
        self.jira_auth = (os.environ["JIRA_USER_EMAIL"], os.environ["JIRA_API_TOKEN"])
        self.gh_headers = {
            "Authorization": f"Bearer {self.pat}",
            "Accept": "application/vnd.github+json",
        }
        self.jira_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def poll_all_repos(self) -> None:
        """Scan all repos from repo-map.json for PR activity."""
        repo_map_path = os.path.join(os.path.dirname(__file__), "..", "repo-map.json")
        with open(repo_map_path) as f:
            data = json.load(f)

        repos = set()
        for route in data.get("routes", []):
            repos.add(route["github_repo"])
        default_repo = data.get("defaults", {}).get("github_repo")
        if default_repo:
            repos.add(default_repo)

        print(f"Polling {len(repos)} repos for PR activity...")

        for repo in repos:
            print(f"\nChecking {repo}...")
            try:
                await self._poll_repo(repo)
            except Exception as e:
                print(f"  Error polling {repo}: {e}", file=sys.stderr)

        print("\nSync complete.")

    async def _poll_repo(self, repo: str) -> None:
        """Check one repo for DevFlow Kit PRs and sync status to Jira."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/pulls",
                headers=self.gh_headers,
                params={"state": "all", "per_page": 30, "sort": "updated", "direction": "desc"},
            )
            resp.raise_for_status()
            prs = resp.json()

        devflow_prs = [
            pr
            for pr in prs
            if any(
                lbl["name"] in ("devflow-kit", "ai-implementation")
                for lbl in pr.get("labels", [])
            )
        ]

        if not devflow_prs:
            print("  No DevFlow Kit PRs found")
            return

        print(f"  Found {len(devflow_prs)} DevFlow Kit PRs")

        for pr in devflow_prs:
            await self._sync_pr(repo, pr)

    async def _sync_pr(self, repo: str, pr: dict) -> None:
        """Sync a single PR's status to Jira."""
        pr_number = pr["number"]
        pr_url = pr["html_url"]
        pr_title = pr.get("title", "")
        pr_branch = pr.get("head", {}).get("ref", "")
        is_merged = pr.get("merged_at") is not None
        is_closed = pr.get("state") == "closed"
        labels = {lbl["name"] for lbl in pr.get("labels", [])}

        issue_key = extract_jira_key(pr_branch) or extract_jira_key(pr_title)
        if not issue_key:
            return

        if not is_closed and "devflow-synced-opened" not in labels:
            print(f"  Syncing PR #{pr_number} opened → {issue_key}")
            await self._comment_jira(
                issue_key,
                f"🔗 Pull request opened\nPR: {pr_url}\nRepo: {repo}",
            )
            await self._transition_jira(issue_key, "In Review")
            await self._add_label(repo, pr_number, "devflow-synced-opened")

        elif is_merged and "devflow-synced-merged" not in labels:
            merged_by = pr.get("merged_by", {}).get("login", "unknown")
            print(f"  Syncing PR #{pr_number} merged → {issue_key}")
            await self._comment_jira(
                issue_key,
                f"✅ Pull request merged\nPR: {pr_url}\nMerged by: {merged_by}",
            )
            await self._transition_jira(issue_key, "Done")
            await self._add_label(repo, pr_number, "devflow-synced-merged")
            await self._check_parent_completion(issue_key)

        elif is_closed and not is_merged and "devflow-synced-merged" not in labels:
            print(f"  Syncing PR #{pr_number} closed → {issue_key}")
            await self._comment_jira(
                issue_key,
                f"⚠️ Pull request closed without merge\nPR: {pr_url}",
            )
            await self._add_label(repo, pr_number, "devflow-synced-merged")

    async def _check_parent_completion(self, subtask_key: str) -> None:
        """If this is a subtask, check if all siblings are done."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.jira_base_url}/rest/api/3/issue/{subtask_key}",
                    auth=self.jira_auth,
                    headers=self.jira_headers,
                )
                resp.raise_for_status()
                issue = resp.json()

            parent = issue.get("fields", {}).get("parent")
            if not parent:
                return

            parent_key = parent["key"]

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.jira_base_url}/rest/api/3/issue/{parent_key}",
                    auth=self.jira_auth,
                    headers=self.jira_headers,
                    params={"fields": "subtasks"},
                )
                resp.raise_for_status()
                siblings = resp.json().get("fields", {}).get("subtasks", [])

            if not siblings:
                return

            done_count = 0
            lines = []
            for sib in siblings:
                status = sib["fields"]["status"]["name"]
                is_done = status.lower() in ("done", "closed", "resolved")
                done_count += is_done
                icon = "✅" if is_done else "⏳"
                lines.append(f"{icon} {sib['key']}: {sib['fields']['summary']} ({status})")

            summary = "\n".join(lines)

            if done_count == len(siblings):
                await self._comment_jira(
                    parent_key,
                    f"🎉 All {len(siblings)} subtasks complete!\n\n{summary}",
                )
                await self._transition_jira(parent_key, "Done")
                print(f"  Parent {parent_key}: all subtasks done → Done")
            else:
                await self._comment_jira(
                    parent_key,
                    f"🔄 Subtask progress: {done_count}/{len(siblings)}\n\n{summary}",
                )

        except Exception as e:
            print(f"  Parent check failed: {e}", file=sys.stderr)

    async def _comment_jira(self, issue_key: str, body: str) -> None:
        payload = {
            "body": {
                "version": 1,
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": body}]},
                ],
            }
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.jira_base_url}/rest/api/3/issue/{issue_key}/comment",
                auth=self.jira_auth,
                headers=self.jira_headers,
                json=payload,
            )
            resp.raise_for_status()

    async def _transition_jira(self, issue_key: str, status: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.jira_base_url}/rest/api/3/issue/{issue_key}/transitions",
                auth=self.jira_auth,
                headers=self.jira_headers,
            )
            resp.raise_for_status()
            transitions = resp.json().get("transitions", [])

            target = next((t for t in transitions if t["name"].lower() == status.lower()), None)
            if not target:
                return

            await client.post(
                f"{self.jira_base_url}/rest/api/3/issue/{issue_key}/transitions",
                auth=self.jira_auth,
                headers=self.jira_headers,
                json={"transition": {"id": target["id"]}},
            )

    async def _add_label(self, repo: str, pr_number: int, label: str) -> None:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels",
                headers=self.gh_headers,
                json={"labels": [label]},
            )


# Entry point for the workflow
async def main() -> None:
    agent = SyncAgent()
    await agent.poll_all_repos()


if __name__ == "__main__":
    asyncio.run(main())
