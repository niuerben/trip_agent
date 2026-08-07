"""FunctionCallAgent 工具循环审计测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.services.observable_function_call_agent import ObservableFunctionCallAgent


def response(content: str = "", tool_calls: list | None = None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls or []))]
    )


def tool_call(name: str):
    return SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(name=name, arguments='{"city": "深圳"}'),
    )


def fake_agent(responses: list, max_iterations: int = 4) -> ObservableFunctionCallAgent:
    agent = object.__new__(ObservableFunctionCallAgent)
    agent._history = []
    agent.max_tool_iterations = max_iterations
    agent.default_tool_choice = "auto"
    agent._get_system_prompt = lambda: "system"
    agent._build_tool_schemas = lambda: [{"type": "function"}]
    agent._invoke_with_tools = lambda *_args, **_kwargs: responses.pop(0)
    agent._extract_message_content = lambda content: content or ""
    agent._parse_function_call_arguments = lambda _arguments: {"city": "深圳"}
    agent._execute_tool_call = lambda _name, _arguments: "tool result"
    agent.add_message = lambda _message: None
    return agent


class AgentLoopLoggingTest(unittest.TestCase):
    def test_logs_model_stop_after_tool_result(self) -> None:
        agent = fake_agent([response(tool_calls=[tool_call("maps_weather")]), response("final plan")])
        events = []
        with patch(
            "backend.app.services.observable_function_call_agent.log_agent_loop",
            side_effect=lambda event, _run_id, **fields: events.append((event, fields)),
        ):
            result = agent.run("规划深圳旅行")

        self.assertEqual(result, "final plan")
        self.assertEqual(events[1][0], "tool_calls_requested")
        self.assertEqual(events[1][1]["tool_names"], ["maps_weather"])
        self.assertEqual(events[-1][1]["termination_reason"], "model_returned_no_tool_calls")

    def test_logs_forced_stop_at_iteration_limit(self) -> None:
        agent = fake_agent(
            [response(tool_calls=[tool_call("maps_weather")]), response("forced final")],
            max_iterations=1,
        )
        events = []
        with patch(
            "backend.app.services.observable_function_call_agent.log_agent_loop",
            side_effect=lambda event, _run_id, **fields: events.append((event, fields)),
        ):
            result = agent.run("规划深圳旅行")

        self.assertEqual(result, "forced final")
        self.assertEqual(events[-2][0], "force_final_response")
        self.assertEqual(events[-2][1]["termination_reason"], "max_tool_iterations_reached")
        self.assertEqual(events[-1][1]["termination_reason"], "forced_final_response")


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证 Agent 工具循环、终止条件和日志记录。")
