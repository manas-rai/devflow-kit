"""AgentRunner — executes agents on the Claude Code CLI.

The runner is the single point of contact with the Claude Code CLI.
It takes an agent definition, assembles the prompt, pipes it to
`claude -p`, captures the output, runs guardrails, and manages
retries and lifecycle hooks.

Usage:
    runner = AgentRunner()
    result = await runner.run(
        agent=RefinementAgent(),
        context=AgentContext(issue_key="PROJ-100", summary="Add avatars", ...)
    )
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field

from framework.base_agent import AgentContext, BaseAgent
from framework.guardrail import GuardrailResult


@dataclass
class ToolCall:
    """A single tool invocation detected in the execution log."""

    tool_name: str
    script: str
    output_snippet: str = ""


@dataclass
class RunResult:
    """The outcome of an agent run."""

    status: str  # "success" | "failure" | "retried"
    execution_log: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    guardrail_results: list[GuardrailResult] = field(default_factory=list)
    attempts: int = 1
    duration_seconds: float = 0.0
    error: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status in ("success", "retried")


class AgentRunner:
    """Executes a BaseAgent by piping its prompt to `claude -p`.

    This is the only class that touches subprocess. Everything else
    in the framework is pure data and declarations.
    """

    def __init__(self, claude_command: str = "claude") -> None:
        self.claude_command = claude_command

    async def run(self, agent: BaseAgent, context: AgentContext) -> RunResult:
        """Execute an agent with the given context.

        Flow:
        1. Call agent.on_start()
        2. Build the prompt (template + tool docs + context)
        3. Pipe to claude -p
        4. Parse execution log for tool calls
        5. Run guardrails
        6. If guardrails fail and retries remain → retry with corrective prompt
        7. Call agent.on_success() or agent.on_failure()
        8. Return RunResult
        """
        start_time = time.time()

        # 1. Lifecycle: on_start
        await agent.on_start(context)

        # 2. Build the initial prompt
        prompt = agent.build_prompt(context)
        attempt = 0
        last_failure = ""

        while attempt <= agent.retry_count:
            attempt += 1

            # On retry, append the failure message
            if attempt > 1 and last_failure:
                await agent.on_retry(context, attempt, last_failure)
                prompt = agent.get_retry_prompt(prompt, last_failure)

            # 3. Execute claude -p
            execution_log = self._invoke_claude(
                prompt=prompt,
                max_turns=agent.max_turns,
                verbose=agent.verbose,
            )

            # 4. Parse tool calls from the log
            tool_calls = self._parse_tool_calls(execution_log, agent)

            # 5. Run guardrails
            guardrail_results = []
            failed_errors = []
            warnings = []

            for guardrail in agent.guardrails:
                result = guardrail.check(execution_log, context.__dict__)
                guardrail_results.append(result)

                if not result.passed:
                    if guardrail.severity == "error":
                        failed_errors.append(f"[{guardrail.name}] {result.message}")
                        print(
                            f"GUARDRAIL FAILED ({guardrail.name}): {result.message}",
                            file=sys.stderr,
                        )
                    else:
                        warnings.append(f"[{guardrail.name}] {result.message}")
                        print(
                            f"GUARDRAIL WARNING ({guardrail.name}): {result.message}",
                            file=sys.stderr,
                        )

            # Log warnings (don't retry for warnings)
            for w in warnings:
                print(f"  ⚠️  {w}", file=sys.stderr)

            # 6. If error guardrails passed, we're done
            if not failed_errors:
                duration = time.time() - start_time
                status = "retried" if attempt > 1 else "success"
                await agent.on_success(context, execution_log)

                return RunResult(
                    status=status,
                    execution_log=execution_log,
                    tool_calls=tool_calls,
                    guardrail_results=guardrail_results,
                    attempts=attempt,
                    duration_seconds=duration,
                )

            # Error guardrails failed — retry if possible
            last_failure = "\n".join(failed_errors)
            if attempt <= agent.retry_count:
                print(
                    f"Retrying (attempt {attempt + 1}/{agent.retry_count + 1})...",
                    file=sys.stderr,
                )

        # All retries exhausted
        duration = time.time() - start_time
        error_msg = f"Agent failed after {attempt} attempts. Last failure: {last_failure}"
        await agent.on_failure(context, error_msg)

        return RunResult(
            status="failure",
            execution_log=execution_log,
            tool_calls=tool_calls,
            guardrail_results=guardrail_results,
            attempts=attempt,
            duration_seconds=duration,
            error=error_msg,
        )

    def _invoke_claude(
        self,
        prompt: str,
        max_turns: int,
        verbose: bool,
    ) -> str:
        """Call the Claude Code CLI and return the full output.

        This is the ONLY subprocess call in the entire framework.
        MCP servers are auto-loaded from .claude/settings.json
        in the working directory.
        """
        cmd = [self.claude_command, "-p", "--output-format", "stream-json", "--max-turns", str(max_turns)]
        if verbose:
            cmd.append("--verbose")

        print(f"Invoking: {' '.join(cmd[:4])}... ({len(prompt)} chars)", file=sys.stderr, flush=True)
        print("MCP servers loaded from .claude/settings.json", file=sys.stderr, flush=True)
        print(f"Full command: {' '.join(cmd)}", file=sys.stderr, flush=True)

        try:
            # Use Popen to stream output in real-time while also capturing it
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Send prompt and close stdin
            stdout_data, stderr_data = proc.communicate(
                input=prompt, timeout=1800
            )

        except FileNotFoundError:
            print("ERROR: 'claude' CLI not found. Is it installed?", file=sys.stderr, flush=True)
            return "ERROR: claude CLI not found"
        except subprocess.TimeoutExpired:
            proc.kill()
            print("ERROR: Claude CLI timed out after 30 minutes", file=sys.stderr, flush=True)
            return "ERROR: claude CLI timed out"

        print(f"\n{'='*60}", file=sys.stderr, flush=True)
        print(f"Claude CLI exit code: {proc.returncode}", file=sys.stderr, flush=True)
        print(f"Stdout length: {len(stdout_data)} chars", file=sys.stderr, flush=True)
        print(f"Stderr length: {len(stderr_data)} chars", file=sys.stderr, flush=True)
        print(f"{'='*60}", file=sys.stderr, flush=True)

        # Print FULL stdout (Claude's response) so it appears in CI logs
        if stdout_data:
            print(f"\n--- CLAUDE STDOUT (full) ---", file=sys.stderr, flush=True)
            print(stdout_data[:5000], file=sys.stderr, flush=True)
            if len(stdout_data) > 5000:
                print(f"... ({len(stdout_data) - 5000} more chars truncated)", file=sys.stderr, flush=True)
            print(f"--- END STDOUT ---\n", file=sys.stderr, flush=True)
        else:
            print("WARNING: Claude produced NO stdout output", file=sys.stderr, flush=True)

        # Print stderr (often contains MCP/tool errors and verbose output)
        if stderr_data:
            print(f"\n--- CLAUDE STDERR (full) ---", file=sys.stderr, flush=True)
            print(stderr_data[:5000], file=sys.stderr, flush=True)
            if len(stderr_data) > 5000:
                print(f"... ({len(stderr_data) - 5000} more chars truncated)", file=sys.stderr, flush=True)
            print(f"--- END STDERR ---\n", file=sys.stderr, flush=True)
        else:
            print("NOTE: Claude produced no stderr output", file=sys.stderr, flush=True)

        if proc.returncode != 0:
            print(f"ERROR: Claude CLI failed with exit code {proc.returncode}", file=sys.stderr, flush=True)

        # Combine stdout and stderr for the full execution log
        full_log = stdout_data
        if stderr_data:
            full_log += f"\n--- STDERR ---\n{stderr_data}"

        return full_log

    def _parse_tool_calls(
        self, execution_log: str, agent: BaseAgent
    ) -> list[ToolCall]:
        """Extract tool invocations from the execution log.

        Detects both Bash tool scripts and MCP tool calls.
        """
        calls = []

        # Detect Bash tool calls (from agent.tools)
        for tool in agent.tools:
            if tool.script in execution_log:
                count = execution_log.count(f"python {tool.script}")
                if count == 0:
                    count = execution_log.count(tool.script)
                for _ in range(max(count, 1)):
                    calls.append(ToolCall(
                        tool_name=tool.name,
                        script=tool.script,
                    ))

        # Detect MCP tool calls (pattern: mcp__server__tool_name)
        import re

        mcp_pattern = r"mcp__(\w+)__(\w+)"
        mcp_matches = re.findall(mcp_pattern, execution_log)
        for server, tool_name in mcp_matches:
            calls.append(ToolCall(
                tool_name=f"mcp__{server}__{tool_name}",
                script=f"mcp:{server}/{tool_name}",
            ))

        return calls
