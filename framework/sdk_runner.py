"""SDKRunner — provider-agnostic agentic loop replacing Claude CLI."""
from __future__ import annotations

import sys
import time

from framework.base_agent import AgentContext, BaseAgent
from framework.runner import RunResult, ToolCall
from framework.providers import get_provider
from framework.tools import get_tools_for_agent, execute_tool


class SDKRunner:
    """Agentic loop that calls LLM providers directly via SDK.

    Replaces the Claude CLI-based AgentRunner for environments where
    ANTHROPIC_API_KEY (or equivalent) is available.

    Usage:
        runner = SDKRunner(provider="anthropic")
        result = await runner.run(agent, context)
    """

    def __init__(self, provider: str = "anthropic", model: str | None = None):
        self.provider_name = provider
        self.provider = get_provider(provider, model)

    async def run(self, agent: BaseAgent, context: AgentContext) -> RunResult:
        """Execute an agent through the provider SDK agentic loop."""
        start_time = time.time()
        await agent.on_start(context)
        prompt = agent.build_prompt(context)
        tools = get_tools_for_agent(agent.name)
        messages = [{"role": "user", "content": "Begin the workflow."}]

        total_in, total_out, total_cached = 0, 0, 0
        all_calls: list[ToolCall] = []
        full_log = ""
        turn = 0

        while turn < agent.max_turns:
            turn += 1
            response = await self.provider.complete(
                system=prompt,
                messages=messages,
                tools=tools,
            )
            total_in += response.input_tokens
            total_out += response.output_tokens
            total_cached += response.cached_tokens

            print(
                f"  Turn {turn}: {response.input_tokens:,} in / {response.output_tokens:,} out"
                f" / {response.cached_tokens:,} cached",
                file=sys.stderr,
            )

            if response.text:
                full_log += response.text + "\n"

            if not response.tool_calls:
                break

            messages.append(self.provider.format_assistant_message(response))
            tool_results = []
            for tc in response.tool_calls:
                print(f"    -> {tc['name']}({list(tc['input'].keys())})", file=sys.stderr)
                result = await execute_tool(tc["name"], tc["input"], context)
                full_log += f"\n[{tc['name']}]: {result[:300]}\n"
                all_calls.append(ToolCall(
                    tool_name=tc["name"],
                    script=tc["name"],
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                ))
                tool_results.append(self.provider.format_tool_result(tc["id"], result))

            messages.append({"role": "user", "content": tool_results})

            if response.stop_reason == "end_turn":
                break

        print(
            f"\nSDK Tokens: {total_in:,} in / {total_out:,} out / {total_cached:,} cached ({turn} turns)",
            file=sys.stderr,
        )

        # Run guardrails
        guardrail_results = []
        failed_errors = []
        for g in agent.guardrails:
            r = g.check(full_log, context.__dict__)
            guardrail_results.append(r)
            if not r.passed and g.severity == "error":
                failed_errors.append(f"[{g.name}] {r.message}")

        duration = time.time() - start_time
        status = "failure" if failed_errors else "success"

        if failed_errors:
            await agent.on_failure(context, "\n".join(failed_errors))
        else:
            await agent.on_success(context, full_log)

        return RunResult(
            status=status,
            execution_log=full_log,
            tool_calls=all_calls,
            guardrail_results=guardrail_results,
            attempts=1,
            duration_seconds=duration,
            error="\n".join(failed_errors),
            input_tokens=total_in,
            output_tokens=total_out,
        )
