"""为 HelloAgents FunctionCallAgent 增加工具循环审计，不改变其决策逻辑。"""

from __future__ import annotations

import time
from typing import Any, Optional, Union
from uuid import uuid4

from hello_agents import FunctionCallAgent
from hello_agents.core.message import Message

from .agent_loop_logging import _summary, log_agent_loop
from .mcp_logging import agent_tool_execution_context


class ObservableFunctionCallAgent(FunctionCallAgent):
    """保留原始 FunctionCallAgent 循环，同时记录每轮的停止或继续原因。"""

    def run(
        self,
        input_text: str,
        *,
        max_tool_iterations: Optional[int] = None,
        tool_choice: Optional[Union[str, dict]] = None,
        **kwargs: Any,
    ) -> str:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._get_system_prompt()}]
        messages.extend({"role": msg.role, "content": msg.content} for msg in self._history)
        messages.append({"role": "user", "content": input_text})

        run_id = uuid4().hex
        started = time.perf_counter()
        tool_schemas = self._build_tool_schemas()
        iterations_limit = (
            max_tool_iterations if max_tool_iterations is not None else self.max_tool_iterations
        )
        effective_tool_choice: Union[str, dict] = (
            tool_choice if tool_choice is not None else self.default_tool_choice
        )
        log_agent_loop(
            "run_start",
            run_id,
            max_tool_iterations=iterations_limit,
            available_tool_count=len(tool_schemas),
            tool_choice=effective_tool_choice,
        )

        if not tool_schemas:
            response_text = self.llm.invoke(messages, **kwargs)
            log_agent_loop(
                "run_end",
                run_id,
                termination_reason="no_registered_tools",
                duration_ms=round((time.perf_counter() - started) * 1000),
                final_response_summary=_summary(response_text),
            )
            self.add_message(Message(input_text, "user"))
            self.add_message(Message(response_text, "assistant"))
            return response_text

        current_iteration = 0
        final_response = ""
        try:
            while current_iteration < iterations_limit:
                iteration = current_iteration + 1
                response = self._invoke_with_tools(
                    messages,
                    tools=tool_schemas,
                    tool_choice=effective_tool_choice,
                    **kwargs,
                )
                assistant_message = response.choices[0].message
                content = self._extract_message_content(assistant_message.content)
                tool_calls = list(assistant_message.tool_calls or [])

                if not tool_calls:
                    final_response = content
                    messages.append({"role": "assistant", "content": final_response})
                    log_agent_loop(
                        "run_end",
                        run_id,
                        iteration=iteration,
                        termination_reason="model_returned_no_tool_calls",
                        duration_ms=round((time.perf_counter() - started) * 1000),
                        final_response_summary=_summary(final_response),
                    )
                    break

                tool_names = [call.function.name for call in tool_calls]
                log_agent_loop(
                    "tool_calls_requested",
                    run_id,
                    iteration=iteration,
                    tool_call_count=len(tool_calls),
                    tool_names=tool_names,
                    assistant_content_summary=_summary(content),
                )
                assistant_payload: dict[str, Any] = {"role": "assistant", "content": content, "tool_calls": []}
                for tool_call in tool_calls:
                    assistant_payload["tool_calls"].append({
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    })
                messages.append(assistant_payload)

                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    arguments = self._parse_function_call_arguments(tool_call.function.arguments)
                    with agent_tool_execution_context(run_id, iteration):
                        result = self._execute_tool_call(tool_name, arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": result,
                    })
                current_iteration += 1

            if current_iteration >= iterations_limit and not final_response:
                log_agent_loop(
                    "force_final_response",
                    run_id,
                    completed_tool_iterations=current_iteration,
                    termination_reason="max_tool_iterations_reached",
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
                final_choice = self._invoke_with_tools(
                    messages,
                    tools=tool_schemas,
                    tool_choice="none",
                    **kwargs,
                )
                final_response = self._extract_message_content(final_choice.choices[0].message.content)
                messages.append({"role": "assistant", "content": final_response})
                log_agent_loop(
                    "run_end",
                    run_id,
                    termination_reason="forced_final_response",
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    final_response_summary=_summary(final_response),
                )
        except Exception as error:
            log_agent_loop(
                "run_error",
                run_id,
                iteration=current_iteration + 1,
                error_type=type(error).__name__,
                error_message=str(error),
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            raise

        self.add_message(Message(input_text, "user"))
        self.add_message(Message(final_response, "assistant"))
        return final_response
