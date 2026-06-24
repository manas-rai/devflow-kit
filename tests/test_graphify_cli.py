"""Tests for the Graphify CLI's route discovery."""

import json
from pathlib import Path

from tools.graphify_cli import load_routes


def _write_map(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "repo-map.json"
    p.write_text(json.dumps(data))
    return p


def test_load_routes_includes_routes_and_default(tmp_path):
    path = _write_map(
        tmp_path,
        {
            "routes": [
                {"github_repo": "org/api", "default_branch": "main"},
                {"github_repo": "org/web", "default_branch": "develop"},
            ],
            "defaults": {"github_repo": "org/api", "default_branch": "main"},
        },
    )
    routes = load_routes(path)
    repos = {r["repo"]: r["branch"] for r in routes}
    # default repo already present as a route — not duplicated
    assert repos == {"org/api": "main", "org/web": "develop"}


def test_load_routes_adds_default_when_absent(tmp_path):
    path = _write_map(
        tmp_path,
        {
            "routes": [{"github_repo": "org/api"}],
            "defaults": {"github_repo": "org/fallback", "default_branch": "trunk"},
        },
    )
    routes = load_routes(path)
    repos = {r["repo"]: r["branch"] for r in routes}
    assert repos == {"org/api": "main", "org/fallback": "trunk"}


def test_load_routes_skips_graph_opted_out(tmp_path):
    path = _write_map(
        tmp_path,
        {
            "routes": [
                {"github_repo": "org/api"},
                {"github_repo": "org/secret", "graph": False},
            ],
            "defaults": {},
        },
    )
    repos = [r["repo"] for r in load_routes(path)]
    assert "org/api" in repos
    assert "org/secret" not in repos
