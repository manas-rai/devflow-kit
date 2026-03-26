"""Tests for BaseAgent and concrete agent definitions."""

from agents.refinement import RefinementAgent
from agents.implementation import ImplementationAgent
from framework.base_agent import AgentContext, BaseAgent
from framework.tool import resolve_repo


class TestAgentContext:
    def test_to_template_vars(self):
        ctx = AgentContext(
            issue_key="PROJ-100",
            project_key="PROJ",
            component="backend",
            summary="Add avatars",
            description="Users need avatars",
            jira_base_url="https://acme.atlassian.net/",
            target_repo="acme/api",
            target_branch="develop",
        )
        vars = ctx.to_template_vars()
        assert vars["{{issue_key}}"] == "PROJ-100"
        assert vars["{{target_repo}}"] == "acme/api"
        assert vars["{{target_branch}}"] == "develop"
        # Strips trailing slash
        assert vars["{{jira_base_url}}"] == "https://acme.atlassian.net"

    def test_empty_description_gets_default(self):
        ctx = AgentContext(description="")
        vars = ctx.to_template_vars()
        assert vars["{{description}}"] == "No description provided."


class TestBaseAgent:
    def test_build_prompt_replaces_vars(self):
        class TestAgent(BaseAgent):
            name = "test"
            prompt_template = "prompts/refine.md"
            tools = [resolve_repo]

        agent = TestAgent()
        ctx = AgentContext(
            issue_key="TEST-1",
            summary="Test ticket",
            target_repo="org/repo",
            jira_base_url="https://test.atlassian.net",
        )
        prompt = agent.build_prompt(ctx)
        assert "TEST-1" in prompt
        assert "org/repo" in prompt
        assert "{{issue_key}}" not in prompt
        # New prompt fetches ticket content via MCP resources, not template vars
        assert "business" in prompt.lower()

    def test_retry_prompt_appends_failure(self):
        agent = BaseAgent()
        retry = agent.get_retry_prompt("Original prompt", "You forgot to create an issue")
        assert "Original prompt" in retry
        assert "You forgot to create an issue" in retry
        assert "IMPORTANT" in retry


class TestRefinementAgent:
    def test_has_bash_tools(self):
        agent = RefinementAgent()
        tool_names = [t.name for t in agent.tools]
        # Only custom Bash tools — Jira/GitHub are via MCP
        assert "resolve_repo" in tool_names

    def test_mcp_handles_jira_github(self):
        """Jira and GitHub tools are NOT in the agent's tools list.
        They come from the devflow MCP server configured in .mcp.json."""
        agent = RefinementAgent()
        tool_names = [t.name for t in agent.tools]
        assert "create_github_issue" not in tool_names
        assert "post_jira_comment" not in tool_names
        assert "create_jira_subtask" not in tool_names

    def test_has_required_guardrails(self):
        agent = RefinementAgent()
        guardrail_names = [g.name for g in agent.guardrails]
        # Refinement no longer creates GitHub issues
        assert "must_create_github_issue" not in guardrail_names
        assert "must_update_jira" in guardrail_names

    def test_max_turns_is_reasonable(self):
        agent = RefinementAgent()
        assert 10 <= agent.max_turns <= 50

    def test_retry_count(self):
        agent = RefinementAgent()
        assert agent.retry_count >= 1

    def test_prompt_loads(self):
        agent = RefinementAgent()
        ctx = AgentContext(
            issue_key="X-1",
            target_repo="org/x",
            jira_base_url="https://x.atlassian.net",
        )
        prompt = agent.build_prompt(ctx)
        assert "X-1" in prompt
        assert "org/x" in prompt
        assert len(prompt) > 500

    def test_supports_re_refinement_context(self):
        """Agent should accept extra context for re-refinement."""
        ctx = AgentContext(
            issue_key="X-1",
            target_repo="org/x",
            jira_base_url="https://x.atlassian.net",
            extra={
                "event_type": "devflow-re-refine",
                "feedback": "Need more detail on testing",
                "github_issue_number": "42",
            },
        )
        assert ctx.extra["event_type"] == "devflow-re-refine"
        assert ctx.extra["feedback"] == "Need more detail on testing"


class TestImplementationAgent:
    def test_has_required_guardrails(self):
        agent = ImplementationAgent()
        guardrail_names = [g.name for g in agent.guardrails]
        assert "must_create_github_issue" in guardrail_names
        assert "must_update_jira" in guardrail_names

    def test_max_turns_is_reasonable(self):
        """Implementation bridge doesn't need too many turns."""
        agent = ImplementationAgent()
        assert agent.max_turns <= 30

    def test_prompt_loads(self):
        agent = ImplementationAgent()
        ctx = AgentContext(
            issue_key="X-1",
            target_repo="org/x",
            jira_base_url="https://x.atlassian.net",
        )
        prompt = agent.build_prompt(ctx)
        assert "X-1" in prompt
        assert "implementation" in prompt.lower()
