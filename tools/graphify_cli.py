"""CLI for building and updating Graphify graphs for target repos.

Subcommands:
    discover --mode onboard|sync   Emit a GitHub Actions matrix of repos to process
    onboard  --repo owner/name     Full build for a newly onboarded repo
    update   --repo owner/name     Incremental update (restores the cache first)

Used by .github/workflows/graphify-onboard.yml (and, later, graphify-sync.yml).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.append(str(Path(__file__).parent.parent))

from tools.graph_store import GraphStore  # noqa: E402
from tools.graphify_engine import count_source_files, run_graphify  # noqa: E402
from tools.repo_map import clone_repo  # noqa: E402

REPO_MAP_PATH = Path(__file__).parent.parent / "repo-map.json"


def load_routes(repo_map_path: Path = REPO_MAP_PATH) -> list[dict[str, str]]:
    """Return ``[{"repo": owner/name, "branch": ...}]`` for every graphable route.

    Routes with ``"graph": false`` are skipped. The default repo is included too.
    """
    data = json.loads(Path(repo_map_path).read_text())
    repos: dict[str, str] = {}
    for route in data.get("routes", []):
        if route.get("graph") is False:
            continue
        repo = route.get("github_repo")
        if repo and repo not in repos:
            repos[repo] = route.get("default_branch", "main")
    defaults = data.get("defaults", {})
    default_repo = defaults.get("github_repo")
    if default_repo and default_repo not in repos:
        repos[default_repo] = defaults.get("default_branch", "main")
    return [{"repo": r, "branch": b} for r, b in repos.items()]


def github_head_sha(repo: str, branch: str) -> str | None:
    """Return the current HEAD commit SHA of ``repo``'s ``branch``, or None."""
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{repo}/commits/{branch}",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["sha"]
    except Exception as e:
        print(f"head sha fetch failed for {repo}@{branch}: {e}", file=sys.stderr)
        return None


def _build_and_upload(repo: str, branch: str, *, incremental: bool) -> None:
    """Clone, run Graphify, and upload the artifacts for one repo."""
    store = GraphStore()
    clone_path = clone_repo(repo, branch)
    cache_restore: Path | None = None
    try:
        max_files = int(os.environ.get("GRAPHIFY_MAX_FILES", "0") or "0")
        if max_files > 0:
            n_files = count_source_files(clone_path)
            if n_files > max_files:
                print(
                    f"⏭️  Skipping {repo}: {n_files} files exceeds "
                    f"GRAPHIFY_MAX_FILES={max_files}",
                    file=sys.stderr,
                )
                return

        if incremental:
            cache_restore = Path(tempfile.mkdtemp(prefix="graphify-cache-"))
            if not store.download_cache(repo, cache_restore):
                # Nothing cached yet — fall back to a full build.
                shutil.rmtree(cache_restore, ignore_errors=True)
                cache_restore = None

        result = run_graphify(clone_path, restore_cache_from=cache_restore)
        # Graphify reports token costs on completion — surface the tail for visibility.
        tail = "\n".join(result.stdout.strip().splitlines()[-5:])
        if tail:
            print(f"graphify output tail:\n{tail}", file=sys.stderr)
        sha = github_head_sha(repo, branch) or ""
        store.upload_graph(
            repo,
            result.report_path,
            result.cache_dir,
            sha,
            updated_at=datetime.now(UTC).isoformat(),
            model=os.environ.get("LLM_MODEL", ""),
        )
        print(f"✅ graph stored for {repo} @ {sha[:8] or 'unknown'}", file=sys.stderr)
    finally:
        shutil.rmtree(clone_path, ignore_errors=True)
        if cache_restore:
            shutil.rmtree(cache_restore, ignore_errors=True)


def cmd_discover(args: argparse.Namespace) -> None:
    """Emit a GitHub Actions matrix of repos to process."""
    routes = load_routes()
    store = GraphStore()
    include: list[dict[str, str]] = []
    for route in routes:
        repo, branch = route["repo"], route["branch"]
        stored_sha = store.head_sha(repo)
        if args.mode == "onboard":
            if args.force or stored_sha is None:
                include.append(route)
        else:  # sync
            live_sha = github_head_sha(repo, branch)
            if live_sha and live_sha != stored_sha:
                include.append({**route, "sha": live_sha})
    print(json.dumps({"include": include}))


def cmd_onboard(args: argparse.Namespace) -> None:
    _build_and_upload(args.repo, args.branch, incremental=False)


def cmd_update(args: argparse.Namespace) -> None:
    _build_and_upload(args.repo, args.branch, incremental=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and update Graphify graphs")
    sub = parser.add_subparsers(dest="command", required=True)

    p_disc = sub.add_parser("discover", help="Emit an Actions matrix of repos to process")
    p_disc.add_argument("--mode", choices=["onboard", "sync"], required=True)
    p_disc.add_argument("--force", action="store_true", help="Include repos even if already built")
    p_disc.set_defaults(func=cmd_discover)

    p_onb = sub.add_parser("onboard", help="Full graph build for a repo")
    p_onb.add_argument("--repo", required=True, help="owner/name")
    p_onb.add_argument("--branch", default="main")
    p_onb.set_defaults(func=cmd_onboard)

    p_upd = sub.add_parser("update", help="Incremental graph update for a repo")
    p_upd.add_argument("--repo", required=True, help="owner/name")
    p_upd.add_argument("--branch", default="main")
    p_upd.set_defaults(func=cmd_update)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
