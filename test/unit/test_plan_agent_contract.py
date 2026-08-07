"""Tests for the four-layer agent contract from spec2code."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.plan_agent import PlanAgent
from backend.app.agents.search_agent import SearchAgent
from backend.app.agents.talk_agent import TalkAgent
from backend.app.agents.validate_agent import ValidateAgent
from backend.app.tool.prompt_transform import normalise_selection_response


class PlanAgentContractTest(unittest.TestCase):
    def test_plan_calls_llm_then_tooluse_until_validation_passes(self) -> None:
        calls = []

        class FakeLLM:
            def invoke(self, messages):
                calls.append(messages)
                return {
                    "think": "test response",
                    "action": {"name": "finish", "arguments": {"value": "done"}},
                }

        validation_calls = []

        def validate(observation):
            validation_calls.append(observation)
            return len(validation_calls) > 1

        planner = PlanAgent(
            llm=FakeLLM(),
            search_agents={},
            validate_agent=ValidateAgent(validate),
            max_iterations=2,
        )

        result = planner.plan("trip requirement", "slow pace")

        self.assertEqual(result, {"passed": True, "result": {"value": "done"}})
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(validation_calls), 2)
        self.assertEqual(validation_calls[0]["action"]["name"], "finish")
        self.assertEqual(validation_calls[1]["action"]["name"], "finish")
        self.assertEqual(calls[0][0]["role"], "user")
        self.assertIn("trip requirementslow pace", calls[0][0]["content"])
        self.assertIn("Think:", planner.prompt)
        self.assertIn("Action:", planner.prompt)
        self.assertIn("Observation:", planner.prompt)

    def test_search_agent_parses_react_action(self) -> None:
        result = SearchAgent.normalise_actions('Action: search_weather[{"city":"深圳"}]')
        self.assertEqual(result[0]["name"], "search_weather")
        self.assertEqual(result[0]["arguments"], {"city": "深圳"})

    def test_selection_response_accepts_double_encoded_json(self) -> None:
        response = normalise_selection_response(
            '"{\\"think\\": \\"提交计划\\", \\"action\\": '
            '{\\"name\\": \\"finish\\", \\"arguments\\": {}}}"'
        )
        self.assertEqual(response["think"], "提交计划")
        self.assertEqual(response["action"]["name"], "finish")

    def test_search_observation_does_not_end_the_loop(self) -> None:
        class FakeLLM:
            def __init__(self) -> None:
                self.responses = iter([
                    {
                        "think": "先查询天气",
                        "action": {"name": "search_weather", "arguments": {"city": "深圳"}},
                    },
                    {
                        "think": "信息充分，提交计划",
                        "action": {"name": "finish", "arguments": {"plan": "深圳三日游"}},
                    },
                ])

            def invoke(self, _messages):
                return next(self.responses)

        class WeatherSearchAgent:
            def tooluse(self, _action):
                return {"result": {"weather": "晴"}}

        validation_calls = []

        def validate(observation):
            validation_calls.append(observation)
            return observation["action"].get("name") == "finish"

        planner = PlanAgent(
            llm=FakeLLM(),
            search_agents={"search_weather": WeatherSearchAgent()},
            validate_agent=ValidateAgent(validate),
        )

        result = planner.plan("规划深圳三日游", "天气舒适")

        self.assertEqual(result["result"]["plan"], "深圳三日游")
        self.assertEqual(len(planner.model_reasons), 2)
        self.assertIn('"weather": "晴"', planner.prompt)
        self.assertEqual([item["action"]["name"] for item in validation_calls], ["search_weather", "finish"])

    def test_plan_executes_a_complete_react_sequence(self) -> None:
        class FakeLLM:
            def __init__(self) -> None:
                self.calls = []
                self.responses = iter([
                    {
                        "think": "先查天气",
                        "action": {
                            "name": "search_weather",
                            "arguments": {"city": "深圳"},
                        },
                    },
                    {
                        "think": "再查景点",
                        "action": {
                            "name": "search_attraction",
                            "arguments": {"city": "深圳", "keywords": "自然风光"},
                        },
                    },
                    {
                        "think": "信息足够，提交计划",
                        "action": {
                            "name": "finish",
                            "arguments": {"plan": "深圳三日游"},
                        },
                    },
                ])

            def invoke(self, messages):
                self.calls.append(messages[0]["content"])
                return next(self.responses)

        tool_order = []

        class FakeSearchAgent:
            def __init__(self, name, result) -> None:
                self.name = name
                self.result = result
                self.calls = []

            def tooluse(self, action):
                self.calls.append(action)
                tool_order.append((self.name, action))
                return {"result": self.result}

        llm = FakeLLM()
        weather = FakeSearchAgent("search_weather", {"weather": "晴"})
        attraction = FakeSearchAgent("search_attraction", {"attraction": "莲花山公园"})
        planner = PlanAgent(
            llm=llm,
            search_agents={
                "search_weather": weather,
                "search_attraction": attraction,
            },
        )

        result = planner.plan("规划深圳三日游", "偏好自然风光")

        self.assertTrue(result["passed"])
        self.assertEqual(result["result"]["plan"], "深圳三日游")
        self.assertEqual(len(llm.calls), 3)
        self.assertEqual(len(weather.calls), 1)
        self.assertEqual(len(attraction.calls), 1)
        self.assertEqual([name for name, _ in tool_order], ["search_weather", "search_attraction"])
        self.assertEqual(weather.calls[0][0]["arguments"], {"city": "深圳"})
        self.assertEqual(
            attraction.calls[0][0]["arguments"],
            {"city": "深圳", "keywords": "自然风光"},
        )
        self.assertIn('"weather": "晴"', llm.calls[1])
        self.assertIn('"attraction": "莲花山公园"', llm.calls[2])
        self.assertEqual(
            planner.prompt.count("Think:"),
            3,
        )
        self.assertEqual(
            planner.prompt.count("Action:"),
            3,
        )
        self.assertEqual(
            planner.prompt.count("Observation:"),
            3,
        )

    def test_plan_keeps_loop_prompt_when_iterations_are_exhausted(self) -> None:
        class FakeLLM:
            def invoke(self, _messages):
                return {"think": "继续思考", "action": None}

        planner = PlanAgent(llm=FakeLLM(), search_agents={}, max_iterations=1)

        result = planner.plan("规划深圳三日游", "偏好美食")

        self.assertFalse(result["passed"])
        self.assertIn("最大循环次数", result["error"])
        self.assertIn("Think: 继续思考", planner.prompt)
        self.assertIn("Action: null", planner.prompt)
        self.assertIn("Observation:", planner.prompt)

    def test_talk_passes_prompts_to_plan_agent(self) -> None:
        class FakePlanAgent:
            def __init__(self):
                self.calls = []

            def plan(self, requirement_prompt, preference_prompt):
                self.calls.append((requirement_prompt, preference_prompt))
                return "planned"

        planner = FakePlanAgent()
        talk_agent = TalkAgent.__new__(TalkAgent)
        talk_agent.plan_agent = planner
        self.assertEqual(talk_agent.talk("visit Shenzhen"), "planned")
        self.assertEqual(planner.calls, [("visit Shenzhen", "")])


if __name__ == "__main__":
    unittest.main()
