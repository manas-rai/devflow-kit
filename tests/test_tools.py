"""Tests for DevFlow Kit tools."""

import json
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).parent.parent / "tools"
RESOLVE = str(TOOLS_DIR / "resolve_repo.py")
BUILD = str(TOOLS_DIR / "build_prompt.py")


def run_resolve(project: str, component: str):
    return subprocess.run(
        [sys.executable, RESOLVE,
         "--project", project, "--component", component],
        capture_output=True,
        text=True,
    )


class TestResolveRepo:
    def test_exact_match(self):
        """CWH project resolves to cloud-waste-hunter."""
        result = run_resolve("CWH", "backend")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "cloud-waste-hunter" in data["github_repo"]

    def test_default_fallback(self):
        """Unknown project falls back to default repo."""
        result = run_resolve("UNKNOWN", "x")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["github_repo"]
        assert data["branch"]

    def test_output_format(self):
        """Output should be JSON with github_repo and branch keys."""
        result = run_resolve("CWH", "")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "/" in data["github_repo"]  # owner/repo format
        assert "branch" in data


class TestBuildPrompt:
    def test_fills_placeholders(self):
        env = {
            "ISSUE_KEY": "TEST-1",
            "PROJECT_KEY": "TEST",
            "COMPONENT": "api",
            "SUMMARY": "Fix the bug",
            "DESCRIPTION": "It crashes on login",
            "JIRA_BASE_URL": "https://test.atlassian.net",
            "TARGET_REPO": "org/api",
            "TARGET_BRANCH": "main",
            "PATH": subprocess.os.environ.get("PATH", ""),
        }
        result = subprocess.run(
            [sys.executable, BUILD],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        output = result.stdout
        assert "TEST-1" in output
        assert "org/api" in output
        assert "test.atlassian.net" in output
        # New prompt uses MCP resources for ticket content,
        # so summary/description may not appear as template vars
        assert "{{issue_key}}" not in output

    def test_missing_env_uses_empty(self):
        env = {
            "ISSUE_KEY": "X-1",
            "PROJECT_KEY": "X",
            "JIRA_BASE_URL": "https://x.atlassian.net",
            "TARGET_REPO": "org/x",
            "PATH": subprocess.os.environ.get("PATH", ""),
        }
        result = subprocess.run(
            [sys.executable, BUILD],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        assert "X-1" in result.stdout
