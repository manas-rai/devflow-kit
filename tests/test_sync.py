"""Tests for the SyncAgent."""

from agents.sync import extract_jira_key


class TestExtractJiraKey:
    def test_from_branch_claude_prefix(self):
        assert extract_jira_key("claude/PROJ-123") == "PROJ-123"

    def test_from_branch_feature_prefix(self):
        assert extract_jira_key("feature/PROJ-456-add-avatar") == "PROJ-456"

    def test_from_pr_title(self):
        assert extract_jira_key("PROJ-789: Fix login bug") == "PROJ-789"

    def test_no_key_found(self):
        assert extract_jira_key("feature/add-avatar-upload") is None

    def test_empty_string(self):
        assert extract_jira_key("") is None

    def test_multiple_keys_returns_first(self):
        assert extract_jira_key("PROJ-1 and PROJ-2") == "PROJ-1"
