"""Tests for guardrails — validation against mock execution logs."""

from framework.guardrail import (
    MaxSubtasks,
    MustCallTool,
    MustCreateGitHubIssue,
    MustUpdateJira,
    NoErrorsInOutput,
)

MOCK_LOG_SUCCESS = """
Thinking about the ticket...
Using mcp__github__get_file_contents to read CLAUDE.md
## CLAUDE.md
FastAPI backend...

Using mcp__github__create_issue in org/api
Created issue: https://github.com/org/api/issues/42

Using mcp__jira__add_comment on PROJ-100
Comment posted successfully.

Using mcp__jira__transition_issue on PROJ-100
Transitioned to In Progress.
"""

MOCK_LOG_NO_ISSUE = """
Thinking about the ticket...
Using mcp__github__get_file_contents to read README.md
This looks like a simple fix. Let me analyze further...
I think the approach should be...
"""

MOCK_LOG_DECOMPOSE = """
Using mcp__devflow-github__create_technical_issue in org/api for PROJ-101
https://github.com/org/api/issues/43
Using mcp__devflow-github__create_technical_issue in org/api for PROJ-102
https://github.com/org/api/issues/44
Using mcp__devflow-github__create_technical_issue in org/api for PROJ-103
https://github.com/org/api/issues/45
Using mcp__jira__add_comment on PROJ-100
Decomposition posted.
"""

MOCK_LOG_ERRORS = """
Using mcp__github__create_issue in org/api
ERROR: Authentication failed
Traceback (most recent call last):
  File "mcp_server", line 50, in handle
"""

CTX = {"issue_key": "PROJ-100", "summary": "Test"}


class TestMustCreateGitHubIssue:
    def test_passes_when_issue_created(self):
        g = MustCreateGitHubIssue()
        result = g.check(MOCK_LOG_SUCCESS, CTX)
        assert result.passed

    def test_fails_when_no_issue(self):
        g = MustCreateGitHubIssue()
        result = g.check(MOCK_LOG_NO_ISSUE, CTX)
        assert not result.passed
        assert "did not create" in result.message

    def test_passes_with_decompose(self):
        g = MustCreateGitHubIssue()
        result = g.check(MOCK_LOG_DECOMPOSE, CTX)
        assert result.passed


class TestMustUpdateJira:
    def test_passes_when_comment_posted(self):
        g = MustUpdateJira()
        result = g.check(MOCK_LOG_SUCCESS, CTX)
        assert result.passed

    def test_fails_when_no_comment(self):
        g = MustUpdateJira()
        result = g.check(MOCK_LOG_NO_ISSUE, CTX)
        assert not result.passed

    def test_severity_is_warn(self):
        g = MustUpdateJira()
        assert g.severity == "warn"


class TestMaxSubtasks:
    def test_passes_under_limit(self):
        g = MaxSubtasks(5)
        result = g.check(MOCK_LOG_DECOMPOSE, CTX)
        assert result.passed  # 3 subtasks, limit is 5

    def test_fails_over_limit(self):
        g = MaxSubtasks(2)
        result = g.check(MOCK_LOG_DECOMPOSE, CTX)
        assert not result.passed
        assert "3" in result.message  # Created 3, max was 2

    def test_passes_with_no_subtasks(self):
        g = MaxSubtasks(5)
        result = g.check(MOCK_LOG_SUCCESS, CTX)
        assert result.passed  # 0 subtasks


class TestNoErrorsInOutput:
    def test_passes_clean_log(self):
        g = NoErrorsInOutput()
        result = g.check(MOCK_LOG_SUCCESS, CTX)
        assert result.passed

    def test_detects_errors(self):
        g = NoErrorsInOutput()
        result = g.check(MOCK_LOG_ERRORS, CTX)
        assert not result.passed

    def test_severity_is_warn(self):
        g = NoErrorsInOutput()
        assert g.severity == "warn"


class TestMustCallTool:
    def test_passes_when_tool_called(self):
        g = MustCallTool("mcp__github__get_file_contents")
        result = g.check(MOCK_LOG_SUCCESS, CTX)
        assert result.passed

    def test_fails_when_tool_not_called(self):
        g = MustCallTool("mcp__jira__create_issue")
        result = g.check(MOCK_LOG_SUCCESS, CTX)
        assert not result.passed
