"""Tests for DevFlow Kit tools."""

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
        result = run_resolve("MYPROJ", "backend")
        assert result.returncode == 0
        parts = result.stdout.strip().split()
        assert parts[0] == "your-org/backend-api"
        assert parts[1] == "main"

    def test_frontend_match(self):
        result = run_resolve("MYPROJ", "frontend")
        assert result.returncode == 0
        assert "your-org/web-app" in result.stdout

    def test_unknown_component_falls_back(self):
        result = run_resolve("MYPROJ", "unknown")
        assert result.returncode == 0
        assert "your-org/backend-api" in result.stdout

    def test_unknown_project_falls_back(self):
        result = run_resolve("NOPE", "x")
        assert result.returncode == 0
        assert "your-org/backend-api" in result.stdout


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
        assert "Fix the bug" in output
        assert "It crashes on login" in output
        assert "org/api" in output
        assert "test.atlassian.net" in output
        assert "{{" not in output

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
