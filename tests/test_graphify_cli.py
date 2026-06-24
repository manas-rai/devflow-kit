"""Tests for the Graphify CLI's route discovery and change detection."""

import argparse
import json
from pathlib import Path

import tools.graphify_cli as cli
from tools.graphify_cli import load_routes


class _FakeStore:
    """Stand-in for GraphStore returning canned stored SHAs."""

    def __init__(self, shas: dict[str, str]):
        self._shas = shas

    def head_sha(self, repo: str) -> str | None:
        return self._shas.get(repo)


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


def _patch(monkeypatch, routes, stored):
    monkeypatch.setattr(cli, "load_routes", lambda *a, **k: routes)
    monkeypatch.setattr(cli, "GraphStore", lambda: _FakeStore(stored))


def test_discover_onboard_emits_only_missing(monkeypatch, capsys):
    routes = [{"repo": "org/a", "branch": "main"}, {"repo": "org/b", "branch": "main"}]
    _patch(monkeypatch, routes, stored={"org/b": "sha"})  # a has no graph yet
    cli.cmd_discover(argparse.Namespace(mode="onboard", force=False))
    out = json.loads(capsys.readouterr().out)
    assert [i["repo"] for i in out["include"]] == ["org/a"]


def test_discover_onboard_force_includes_all(monkeypatch, capsys):
    routes = [{"repo": "org/a", "branch": "main"}]
    _patch(monkeypatch, routes, stored={"org/a": "sha"})  # already built
    cli.cmd_discover(argparse.Namespace(mode="onboard", force=True))
    out = json.loads(capsys.readouterr().out)
    assert [i["repo"] for i in out["include"]] == ["org/a"]


def test_discover_sync_emits_only_changed(monkeypatch, capsys):
    routes = [{"repo": "org/a", "branch": "main"}, {"repo": "org/b", "branch": "main"}]
    _patch(monkeypatch, routes, stored={"org/a": "sha-old", "org/b": "sha-cur"})
    live = {"org/a": "sha-new", "org/b": "sha-cur"}  # only a moved
    monkeypatch.setattr(cli, "github_head_sha", lambda repo, branch: live[repo])
    cli.cmd_discover(argparse.Namespace(mode="sync", force=False))
    out = json.loads(capsys.readouterr().out)
    assert [i["repo"] for i in out["include"]] == ["org/a"]
    assert out["include"][0]["sha"] == "sha-new"


def test_discover_sync_skips_unfetchable_head(monkeypatch, capsys):
    routes = [{"repo": "org/a", "branch": "main"}]
    _patch(monkeypatch, routes, stored={"org/a": "sha-old"})
    monkeypatch.setattr(cli, "github_head_sha", lambda repo, branch: None)  # API failed
    cli.cmd_discover(argparse.Namespace(mode="sync", force=False))
    out = json.loads(capsys.readouterr().out)
    assert out["include"] == []
