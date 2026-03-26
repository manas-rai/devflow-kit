"""Tests for AgentRunner — lifecycle, guardrails, retries.

Uses a mock agent and patches subprocess to avoid calling the real Claude CLI.
"""

from unittest.mock import MagicMock, patch

import pytest

from framework.base_agent import AgentContext, BaseAgent
from framework.guardrail import MustCreateGitHubIssue
from framework.runner import AgentRunner
from framework.tool import resolve_repo

MOCK_LOG_SUCCESS = (
    "Using mcp__devflow-github__create_technical_issue in org/api\n"
    "https://github.com/org/api/issues/42\n"
    "Using mcp__devflow-jira__post_jira_comment on PROJ-100\n"
    "Comment posted.\n"
)

MOCK_LOG_NO_ISSUE = "Analyzing the ticket...\nThis looks complex.\n"


class MockAgent(BaseAgent):
    name = "mock_agent"
    prompt_template = "prompts/refine.md"
    tools = [resolve_repo]
    guardrails = [MustCreateGitHubIssue()]
    max_turns = 5
    retry_count = 1


def make_context() -> AgentContext:
    return AgentContext(
        issue_key="PROJ-100",
        summary="Test",
        target_repo="org/api",
        jira_base_url="https://test.atlassian.net",
    )


def mock_popen_success(*args, **kwargs):
    """Mock subprocess.Popen that returns success output."""
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (MOCK_LOG_SUCCESS, "")
    mock_proc.returncode = 0
    return mock_proc


def mock_popen_no_issue(*args, **kwargs):
    """Mock subprocess.Popen that returns output without issue creation."""
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (MOCK_LOG_NO_ISSUE, "")
    mock_proc.returncode = 0
    return mock_proc


class TestAgentRunnerSuccess:
    @pytest.mark.asyncio
    async def test_successful_run(self):
        runner = AgentRunner()
        agent = MockAgent()
        ctx = make_context()

        with patch("subprocess.Popen", side_effect=mock_popen_success):
            result = await runner.run(agent, ctx)

        assert result.succeeded
        assert result.status == "success"
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_captures_mcp_tool_calls(self):
        runner = AgentRunner()
        agent = MockAgent()
        ctx = make_context()

        with patch("subprocess.Popen", side_effect=mock_popen_success):
            result = await runner.run(agent, ctx)

        tool_names = [tc.tool_name for tc in result.tool_calls]
        assert "mcp__devflow-github__create_technical_issue" in tool_names
        assert "mcp__devflow-jira__post_jira_comment" in tool_names


class TestAgentRunnerRetry:
    @pytest.mark.asyncio
    async def test_retries_on_guardrail_failure(self):
        """First call returns no issue, second returns success."""
        runner = AgentRunner()
        agent = MockAgent()
        agent.retry_count = 1
        ctx = make_context()

        call_count = 0

        def alternating_mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_popen_no_issue()
            return mock_popen_success()

        with patch("subprocess.Popen", side_effect=alternating_mock):
            result = await runner.run(agent, ctx)

        assert result.succeeded
        assert result.status == "retried"
        assert result.attempts == 2

    @pytest.mark.asyncio
    async def test_fails_after_all_retries(self):
        runner = AgentRunner()
        agent = MockAgent()
        agent.retry_count = 1
        ctx = make_context()

        with patch("subprocess.Popen", side_effect=mock_popen_no_issue):
            result = await runner.run(agent, ctx)

        assert not result.succeeded
        assert result.status == "failure"
        assert result.attempts == 2
        assert "did not create" in result.error


class TestAgentRunnerLifecycle:
    @pytest.mark.asyncio
    async def test_on_start_called(self):
        runner = AgentRunner()
        agent = MockAgent()
        ctx = make_context()
        started = []

        async def track_start(context):
            started.append(True)

        agent.on_start = track_start

        with patch("subprocess.Popen", side_effect=mock_popen_success):
            await runner.run(agent, ctx)

        assert started == [True]

    @pytest.mark.asyncio
    async def test_on_failure_called(self):
        runner = AgentRunner()
        agent = MockAgent()
        agent.retry_count = 0  # No retries
        ctx = make_context()
        failures = []

        async def track_failure(context, error):
            failures.append(error)

        agent.on_failure = track_failure

        with patch("subprocess.Popen", side_effect=mock_popen_no_issue):
            await runner.run(agent, ctx)

        assert len(failures) == 1
        assert "did not create" in failures[0]
