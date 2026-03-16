"""Tests for the Tool framework class."""

from framework.tool import ALL_TOOLS, Tool, ToolArg, resolve_repo


class TestToolDocs:
    def test_generate_usage_required_args(self):
        tool = Tool(
            name="test_tool",
            description="A test tool",
            script="tools/test.py",
            args=[
                ToolArg("--repo", "Target repo"),
                ToolArg("--title", "Issue title"),
            ],
        )
        usage = tool.generate_usage()
        assert "python tools/test.py" in usage
        assert '--repo "<Target repo>"' in usage
        assert '--title "<Issue title>"' in usage

    def test_generate_usage_optional_args(self):
        tool = Tool(
            name="test_tool",
            description="A test tool",
            script="tools/test.py",
            args=[
                ToolArg("--branch", "Branch name", required=False, default="main"),
            ],
        )
        usage = tool.generate_usage()
        assert "(default: main)" in usage

    def test_generate_docs_includes_all_sections(self):
        tool = Tool(
            name="my_tool",
            description="Does something useful",
            script="tools/my_tool.py",
            args=[ToolArg("--input", "The input file")],
        )
        docs = tool.generate_docs()
        assert "### my_tool" in docs
        assert "Does something useful" in docs
        assert "python tools/my_tool.py" in docs
        assert "--input" in docs

    def test_parse_output_default(self):
        tool = Tool(name="t", description="t", script="t.py")
        assert tool.parse_output("  hello world  \n") == "hello world"


class TestBuiltinTools:
    def test_resolve_repo_has_required_args(self):
        arg_flags = [a.flag for a in resolve_repo.args]
        assert "--project" in arg_flags
        assert "--component" in arg_flags

    def test_only_custom_tools_remain(self):
        """MCP handles Jira/GitHub — only custom routing stays as Bash."""
        assert len(ALL_TOOLS) == 1
        assert ALL_TOOLS[0].name == "resolve_repo"

    def test_all_tools_have_scripts(self):
        for tool in ALL_TOOLS:
            assert tool.script.startswith("tools/")
            assert tool.name
            assert tool.description
