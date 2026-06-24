"""Tests for repo-map engine selection in run_agent (Graphify consumption)."""

from types import SimpleNamespace

import run_agent


class _FakeStore:
    def __init__(self, report=None, meta=None, raises=False):
        self._report = report
        self._meta = meta
        self._raises = raises

    def read_report(self, repo):
        if self._raises:
            raise RuntimeError("boom")
        return self._report

    def get_repo_meta(self, repo):
        return self._meta


def _patch_store(monkeypatch, store):
    monkeypatch.setattr("tools.graph_store.GraphStore", lambda *a, **k: store)


def test_fetch_graph_report_returns_report_with_header(monkeypatch):
    meta = SimpleNamespace(last_sha="abcdef1234", updated_at="2026-06-24T00:00:00Z")
    _patch_store(monkeypatch, _FakeStore(report="## Community Hubs\nauth, billing", meta=meta))
    out = run_agent._fetch_graph_report("org/repo", "main")
    assert out is not None
    assert "Community Hubs" in out
    assert "abcdef12" in out  # short sha in header


def test_fetch_graph_report_none_when_missing(monkeypatch):
    _patch_store(monkeypatch, _FakeStore(report=None))
    assert run_agent._fetch_graph_report("org/repo", "main") is None


def test_fetch_graph_report_swallows_errors(monkeypatch):
    _patch_store(monkeypatch, _FakeStore(raises=True))
    assert run_agent._fetch_graph_report("org/repo", "main") is None


def test_generate_repo_map_uses_graphify_when_enabled(monkeypatch):
    monkeypatch.setenv("REPO_MAP_ENGINE", "graphify")
    monkeypatch.setattr(run_agent, "_fetch_graph_report", lambda repo, branch: "GRAPH-REPORT")
    assert run_agent._generate_repo_map("org/repo", "main") == "GRAPH-REPORT"


def test_generate_repo_map_falls_back_to_ast(monkeypatch):
    """When graphify is enabled but no graph exists, fall through to the AST path."""
    monkeypatch.setenv("REPO_MAP_ENGINE", "graphify")
    monkeypatch.setattr(run_agent, "_fetch_graph_report", lambda repo, branch: None)

    called = {}

    def fake_run(cmd, **kwargs):
        called["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="AST-MAP", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    out = run_agent._generate_repo_map("org/repo", "main")
    assert out == "AST-MAP"
    assert "tools/repo_map.py" in called["cmd"]


def test_generate_repo_map_ast_by_default(monkeypatch):
    monkeypatch.delenv("REPO_MAP_ENGINE", raising=False)

    def boom(repo, branch):  # should never be called in ast mode
        raise AssertionError("graphify should not run by default")

    monkeypatch.setattr(run_agent, "_fetch_graph_report", boom)
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="AST-MAP", stderr=""),
    )
    assert run_agent._generate_repo_map("org/repo", "main") == "AST-MAP"
