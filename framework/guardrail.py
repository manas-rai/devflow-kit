"""Guardrails — post-execution validators for agent runs.

After Claude finishes its agentic loop, guardrails inspect the execution
log (full stdout from claude -p) and determine whether the run meets
quality and safety criteria.

If a guardrail fails:
  - severity="warn": logged, but run still counts as success
  - severity="error": triggers retry (up to agent's retry_count), then fails
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class GuardrailResult:
    passed: bool
    message: str = ""


@dataclass
class Guardrail:
    """Base class for all guardrails.

    Subclass this and implement check() to create custom guardrails.
    """

    name: str
    description: str
    severity: str = "error"  # "error" or "warn"

    def check(self, execution_log: str, context: dict) -> GuardrailResult:
        """Validate the execution log. Override this method.

        Args:
            execution_log: Full stdout from the claude -p run.
            context: The agent's input context (issue_key, summary, etc.)

        Returns:
            GuardrailResult with passed=True/False and a message.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Built-in guardrails
# ---------------------------------------------------------------------------


class MustCallTool(Guardrail):
    """Ensure Claude called at least one specific tool during execution."""

    def __init__(self, tool_script: str, severity: str = "error"):
        super().__init__(
            name=f"must_call_{tool_script.split('/')[-1].replace('.py', '')}",
            description=f"Agent must call {tool_script}",
            severity=severity,
        )
        self.tool_script = tool_script

    def check(self, execution_log: str, context: dict) -> GuardrailResult:
        if self.tool_script in execution_log:
            return GuardrailResult(passed=True)
        return GuardrailResult(
            passed=False,
            message=(
                f"Agent did not call {self.tool_script}."
                " It must take action, not just analyze."
            ),
        )


class MustCreateGitHubIssue(Guardrail):
    """Ensure Claude created at least one GitHub issue."""

    def __init__(self):
        super().__init__(
            name="must_create_github_issue",
            description="Agent must create at least one GitHub issue with @claude",
            severity="error",
        )

    def check(self, execution_log: str, context: dict) -> GuardrailResult:
        # Check for MCP tool call or legacy bash script
        indicators = [
            "mcp__devflow-github__create_technical_issue",
            "mcp__devflow__create_technical_issue",
            "create_technical_issue",
            "create_issue",
            "issues/",  # GitHub issue URL in output
        ]
        if any(ind in execution_log for ind in indicators):
            return GuardrailResult(passed=True)
        return GuardrailResult(
            passed=False,
            message=(
                "Agent did not create any GitHub issues."
                " The ticket must result in at least one"
                " @claude issue."
            ),
        )


class MustUpdateJira(Guardrail):
    """Ensure Claude updated Jira (description or comment)."""

    def __init__(self):
        super().__init__(
            name="must_update_jira",
            description="Agent must update Jira (description or comment)",
            severity="warn",
        )

    def check(self, execution_log: str, context: dict) -> GuardrailResult:
        indicators = [
            "mcp__devflow-jira__update_jira_description",
            "mcp__devflow-jira__post_jira_comment",
            "update_jira_description",
            "post_jira_comment",
            "add_comment",
        ]
        if any(ind in execution_log for ind in indicators):
            return GuardrailResult(passed=True)
        return GuardrailResult(
            passed=False,
            message=(
                "Agent did not update Jira."
                " Team won't know what happened."
            ),
        )


class MustCreatePullRequest(Guardrail):
    """Ensure Claude created at least one pull request."""

    def __init__(self):
        super().__init__(
            name="must_create_pull_request",
            description="Agent must create at least one pull request",
            severity="error",
        )

    def check(self, execution_log: str, context: dict) -> GuardrailResult:
        indicators = [
            "mcp__devflow-github__create_pull_request",
            "mcp__devflow__create_pull_request",
            "create_pull_request",
            "pull/",  # GitHub PR URL in output
        ]
        if any(ind in execution_log for ind in indicators):
            return GuardrailResult(passed=True)
        return GuardrailResult(
            passed=False,
            message=(
                "Agent did not create any pull requests."
                " The implementation must result in a PR."
            ),
        )


class MaxSubtasks(Guardrail):
    """Ensure Claude didn't create more than N subtasks."""

    def __init__(self, max_count: int = 5):
        super().__init__(
            name=f"max_subtasks_{max_count}",
            description=f"Agent must not create more than {max_count} subtasks",
            severity="error",
        )
        self.max_count = max_count

    def check(self, execution_log: str, context: dict) -> GuardrailResult:
        # Count both MCP and legacy Bash subtask creation calls
        count = 0
        for indicator in [
            "mcp__jira__create_issue",
            "create_subtask",
            "tools/create_jira_subtask.py",
        ]:
            count += execution_log.count(indicator)
        # Avoid double-counting — take the max of individual indicators
        count = max(
            execution_log.count("mcp__jira__create_issue"),
            execution_log.count("tools/create_jira_subtask.py"),
            0,
        )
        if count <= self.max_count:
            return GuardrailResult(passed=True)
        return GuardrailResult(
            passed=False,
            message=(
                f"Agent created {count} subtasks (max: {self.max_count}). "
                f"Over-decomposition creates more coordination"
                f" overhead than it saves."
            ),
        )


class NoErrorsInOutput(Guardrail):
    """Check that no tool calls returned errors."""

    def __init__(self):
        super().__init__(
            name="no_errors_in_output",
            description="No tool calls should have returned error responses",
            severity="warn",
        )

    def check(self, execution_log: str, context: dict) -> GuardrailResult:
        error_patterns = [
            r"ERROR:",
            r"HTTP Error \d{3}",
            r"raise_for_status",
            r"Traceback \(most recent call last\)",
        ]
        errors_found = []
        for pattern in error_patterns:
            matches = re.findall(pattern, execution_log)
            errors_found.extend(matches)

        if not errors_found:
            return GuardrailResult(passed=True)
        return GuardrailResult(
            passed=False,
            message=f"Tool errors detected: {errors_found[:3]}",
        )


class ChecklistCompleted(Guardrail):
    """Ensure the agent completed all checkboxes in its outputs."""

    def __init__(self):
        super().__init__(
            name="checklist_completed",
            description="Agent must check all boxes (- [x]) and not leave any open (- [ ])",
            severity="warn",
        )

    def check(self, execution_log: str, context: dict) -> GuardrailResult:
        # Fails if any unresolved markdown checkboxes were generated
        if "- [ ]" in execution_log or "- []" in execution_log or "* [ ]" in execution_log:
            return GuardrailResult(
                passed=False,
                message=(
                    "Found unchecked checklist items ('- [ ]') in the agent output. "
                    "Ensure all acceptance criteria and derived tasks are fully completed."
                ),
            )
        return GuardrailResult(passed=True)
