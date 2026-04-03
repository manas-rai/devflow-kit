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

import json
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
    input_tokens: int = 0
    output_tokens: int = 0

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
        total_input_tokens = 0
        total_output_tokens = 0

        while attempt <= agent.retry_count:
            attempt += 1

            # On retry, append the failure message
            if attempt > 1 and last_failure:
                await agent.on_retry(context, attempt, last_failure)
                prompt = agent.get_retry_prompt(prompt, last_failure)

            # 3. Execute claude -p
            execution_log, in_tok, out_tok = self._invoke_claude(
                prompt=prompt,
                max_turns=agent.max_turns,
                verbose=agent.verbose,
                allowed_tools=agent.allowed_tools,
            )
            total_input_tokens += in_tok
            total_output_tokens += out_tok

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
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
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
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

    def _invoke_claude(
        self,
        prompt: str,
        max_turns: int,
        verbose: bool,
        allowed_tools: list[str] | None = None,
    ) -> tuple[str, int, int]:
        """Call the Claude Code CLI and return (output, input_tokens, output_tokens).

        This is the ONLY subprocess call in the entire framework.
        MCP servers are auto-loaded from .mcp.json in the working directory.
        """
        cmd = [
            self.claude_command, "-p",
            "--max-turns", str(max_turns),
            "--output-format", "json",
        ]
        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])
        if verbose:
            cmd.append("--verbose")

        print(f"Invoking: {' '.join(cmd[:3])}... ({len(prompt)} chars)", file=sys.stderr, flush=True)

        input_tokens = 0
        output_tokens = 0

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout_data, stderr_data = proc.communicate(
                input=prompt, timeout=1800
            )
        except FileNotFoundError:
            print("ERROR: 'claude' CLI not found.", file=sys.stderr, flush=True)
            return "ERROR: claude CLI not found", 0, 0
        except subprocess.TimeoutExpired:
            proc.kill()
            print("ERROR: Claude CLI timed out after 30 minutes", file=sys.stderr, flush=True)
            return "ERROR: claude CLI timed out", 0, 0

        print(f"Claude CLI exit code: {proc.returncode}", file=sys.stderr, flush=True)
        print(f"Output: {len(stdout_data)} chars stdout, {len(stderr_data)} chars stderr", file=sys.stderr, flush=True)

        # Parse JSON output for token tracking and result text
        result_text = stdout_data
        try:
            parsed = json.loads(stdout_data)

            # Claude CLI --output-format json returns a JSON array of messages:
            # [{"type":"system",...}, {"type":"assistant","message":{"usage":{...}}}, ...]
            # The last element with type "result" contains the final text.
            if isinstance(parsed, list):
                # Extract final result text
                for item in reversed(parsed):
                    if isinstance(item, dict):
                        # Look for the final result entry
                        if item.get("type") == "result":
                            result_text = item.get("result", "")
                            input_tokens = item.get("total_input_tokens", 0) or item.get("input_tokens", 0)
                            output_tokens = item.get("total_output_tokens", 0) or item.get("output_tokens", 0)
                            break
                        # Or extract from the last assistant message content
                        if item.get("type") == "assistant" and "message" in item:
                            msg = item["message"]
                            # Get text from content blocks
                            for block in msg.get("content", []):
                                if isinstance(block, dict) and block.get("type") == "text":
                                    result_text = block.get("text", "")

                # Sum tokens from ALL assistant messages if not found in result entry
                if input_tokens == 0:
                    for item in parsed:
                        if isinstance(item, dict) and item.get("type") == "assistant":
                            usage = item.get("message", {}).get("usage", {})
                            input_tokens += usage.get("input_tokens", 0)
                            input_tokens += usage.get("cache_creation_input_tokens", 0)
                            input_tokens += usage.get("cache_read_input_tokens", 0)
                            output_tokens += usage.get("output_tokens", 0)

            # Single object format (older CLI versions)
            elif isinstance(parsed, dict):
                result_text = parsed.get("result", stdout_data)
                input_tokens = parsed.get("input_tokens", 0)
                output_tokens = parsed.get("output_tokens", 0)

            if input_tokens or output_tokens:
                print(
                    f"\U0001f4ca Tokens: {input_tokens:,} input / {output_tokens:,} output",
                    file=sys.stderr, flush=True,
                )

        except (json.JSONDecodeError, TypeError) as e:
            # Not JSON — fall back to raw text
            print(f"JSON parse note: {e}", file=sys.stderr, flush=True)

        if result_text:
            print(f"\n--- CLAUDE OUTPUT ---", file=sys.stderr, flush=True)
            print(result_text[:3000], file=sys.stderr, flush=True)
            if len(result_text) > 3000:
                print(f"... ({len(result_text) - 3000} more chars)", file=sys.stderr, flush=True)
            print(f"--- END OUTPUT ---\n", file=sys.stderr, flush=True)
        else:
            print("WARNING: Claude produced NO output", file=sys.stderr, flush=True)

        if stderr_data:
            print(f"STDERR: {stderr_data[:1000]}", file=sys.stderr, flush=True)

        if proc.returncode != 0:
            print(f"ERROR: exit code {proc.returncode}", file=sys.stderr, flush=True)

        # full_log uses raw stdout so guardrails can scan for tool call names
        # (the JSON array contains all tool_use entries that guardrails look for)
        full_log = stdout_data
        if stderr_data:
            full_log += f"\n--- STDERR ---\n{stderr_data}"

        return full_log, input_tokens, output_tokens

    def _parse_tool_calls(
        self, execution_log: str, agent: BaseAgent
    ) -> list[ToolCall]:
        """Extract actual tool invocations from the JSON execution log.

        Parses the JSON array to find tool_use content blocks in assistant
        messages, rather than doing naive string matching which catches
        tool names in the system init listing.
        """
        calls = []

        try:
            parsed = json.loads(execution_log)
            if not isinstance(parsed, list):
                return calls

            for item in parsed:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "assistant":
                    continue

                message = item.get("message", {})
                for block in message.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_name = block.get("name", "")
                        calls.append(ToolCall(
                            tool_name=tool_name,
                            script=tool_name,
                        ))

        except (json.JSONDecodeError, TypeError):
            # Fallback: regex-based detection for non-JSON output (e.g. tests)
            import re
            mcp_pattern = r'(mcp__[\w-]+__\w+)'
            for match in re.finditer(mcp_pattern, execution_log):
                tool_name = match.group(1)
                calls.append(ToolCall(
                    tool_name=tool_name,
                    script=tool_name,
                ))

        return calls
