#!/usr/bin/env python3
"""Resolve a Jira project/component to a target GitHub repo.

Usage:
    python tools/resolve_repo.py --project MYPROJ --component backend

Output (stdout):
    org/backend-api main
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--component", default="")
    args = parser.parse_args()

    repo_map_path = Path(__file__).parent.parent / "repo-map.json"
    with open(repo_map_path) as f:
        data = json.load(f)

    # Exact match
    for route in data.get("routes", []):
        if (
            route["jira_project"] == args.project
            and route.get("component", "") == args.component
        ):
            print(f"{route['github_repo']} {route.get('default_branch', 'main')}")
            return

    # Fallback
    defaults = data.get("defaults", {})
    repo = defaults.get("github_repo", "")
    branch = defaults.get("default_branch", "main")
    if repo:
        print(f"{repo} {branch}")
    else:
        print("ERROR: No matching route and no defaults configured", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
