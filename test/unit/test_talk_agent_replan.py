"""TalkAgent 对话、重规划与安全降级行为测试。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.talk_agent import TalkAgent
from backend.app.models.schemas import Preference, TalkMessage, TalkRequest


class FakeDialogueAgent:
    def __init__(self, replies: list[str]) -> None:
        self.replies = iter(replies)
        self.prompts: list[str] = []

    def run(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self.replies)


class FakePlanAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def plan(self, requirement_prompt: str, preference_prompt: str) -> dict[str, bool]:
        self.calls.append((requirement_prompt, preference_prompt))
        return {"passed": True}


def response(**payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


class TalkAgentReplanTest(unittest.TestCase):
    def build_agent(self, main_reply: str, suggestion_replies: list[str] | None = None) -> TalkAgent:
        agent = object.__new__(TalkAgent)
        agent.agent = FakeDialogueAgent([main_reply])
        agent.suggestion_agent = FakeDialogueAgent(suggestion_replies or [])
        return agent

    @staticmethod
    def suggestions() -> list[str]:
        return ["安排在上午", "增加附近午餐", "减少一处景点"]

    def test_talk_forwards_requirement_and_preference_to_plan_agent(self) -> None:
        plan_agent = FakePlanAgent()
        agent = object.__new__(TalkAgent)
        agent.plan_agent = plan_agent
        request = TalkRequest(
            city="深圳",
            preference=Preference(prompt="偏好校园和慢节奏"),
            message="规划两日校园路线",
        )

        result = agent.talk(request)
        print(f'对话后{result}')
        self.assertEqual(result, {"passed": True})
        self.assertEqual(plan_agent.calls[0][1], "偏好校园和慢节奏")
        self.assertIn("当前旅行计划目的地: 深圳", plan_agent.calls[0][0])
        self.assertIn("用户: 规划两日校园路线", plan_agent.calls[0][0])

    def test_build_prompt_keeps_city_plan_preference_and_history_order(self) -> None:
        agent = object.__new__(TalkAgent)
        prompt = agent._build_prompt(TalkRequest(
            city="深圳",
            plan_context="第 1 天安排深圳技术大学",
            preference=Preference(prompt="偏好校园和慢节奏"),
            messages=[
                TalkMessage(role="user", content="我喜欢大学校园"),
                TalkMessage(role="assistant", content="我会优先安排校园路线"),
            ],
            message="第 2 天加一处公园",
        ))

        expected_fragments = [
            "当前旅行计划目的地: 深圳",
            "当前行程摘要: 第 1 天安排深圳技术大学",
            "已知长期偏好: 偏好校园和慢节奏",
            "用户: 我喜欢大学校园",
            "顾问: 我会优先安排校园路线",
            "用户: 第 2 天加一处公园",
        ]
        positions = [prompt.index(fragment) for fragment in expected_fragments]
        self.assertEqual(positions, sorted(positions))

    def test_chat_uses_model_suggestions_without_fallback(self) -> None:
        agent = self.build_agent(response(
            reply="可以安排校园与美食路线。",
            intent="chat",
            change_request=None,
            change_set=None,
            top_suggestions=self.suggestions(),
            preference=None,
            done=False,
        ))

        result = agent.chat(TalkRequest(city="深圳", message="推荐一个轻松路线"))

        self.assertEqual(result.intent, "chat")
        self.assertEqual(result.top_suggestions, self.suggestions())
        self.assertEqual(agent.suggestion_agent.prompts, [])

    def test_chat_generates_top3_when_main_reply_omits_them(self) -> None:
        agent = self.build_agent(
            response(
                reply="可以，我来为你调整。",
                intent="chat",
                change_request=None,
                change_set=None,
                preference=None,
                done=True,
            ),
            [response(top_suggestions=["增加一处美食", "把第二天放慢", "查看附近咖啡店"])],
        )

        result = agent.chat(TalkRequest(city="深圳", message="给我推荐坪山美食"))

        self.assertEqual(result.top_suggestions, ["增加一处美食", "把第二天放慢", "查看附近咖啡店"])
        self.assertEqual(len(agent.suggestion_agent.prompts), 1)
        self.assertIn("当前旅行计划目的地: 深圳", agent.suggestion_agent.prompts[0])

    def test_chat_builds_delete_attraction_changeset(self) -> None:
        agent = self.build_agent(response(
            reply="好的，移除寺庙景点。",
            intent="replan",
            change_request="移除寺庙景点",
            change_set={"operations": [{
                "operation": "delete_attraction",
                "selector": {"semantic": "寺庙"},
            }]},
            top_suggestions=self.suggestions(),
            preference=None,
            done=True,
        ))

        result = agent.chat(TalkRequest(message="把寺庙景点删掉"))

        operation = result.change_set.operations[0]
        self.assertEqual(result.intent, "replan")
        self.assertEqual(operation.operation, "delete_attraction")
        self.assertEqual(operation.selector.semantic, "寺庙")

    def test_chat_builds_replace_attraction_changeset(self) -> None:
        agent = self.build_agent(response(
            reply="好的，将马峦山替换为大学。",
            intent="replan",
            change_request="把马峦山改成大学",
            change_set={"operations": [{
                "operation": "replace_attraction",
                "selector": {"name": "马峦山"},
                "target": {"semantic": "大学"},
            }]},
            top_suggestions=self.suggestions(),
            preference=None,
            done=True,
        ))

        result = agent.chat(TalkRequest(message="把马峦山改成大学"))

        operation = result.change_set.operations[0]
        self.assertEqual(operation.operation, "replace_attraction")
        self.assertEqual(operation.selector.name, "马峦山")
        self.assertEqual(operation.target.semantic, "大学")

    def test_chat_builds_add_attraction_changeset(self) -> None:
        agent = self.build_agent(response(
            reply="好的，已将第 2 天增加深圳技术大学。",
            intent="replan",
            change_request="第 2 天增加深圳技术大学",
            change_set={"operations": [{
                "operation": "add_attraction",
                "selector": {"day_index": 1},
                "target": {"semantic": "深圳技术大学"},
            }]},
            top_suggestions=self.suggestions(),
            preference=None,
            done=True,
        ))

        result = agent.chat(TalkRequest(message="第 2 天加深圳技术大学"))

        operation = result.change_set.operations[0]
        self.assertEqual(operation.operation, "add_attraction")
        self.assertEqual(operation.selector.day_index, 1)
        self.assertEqual(operation.target.semantic, "深圳技术大学")

    def test_chat_builds_full_replan_changeset(self) -> None:
        agent = self.build_agent(response(
            reply="好的，我会重新规划整个行程。",
            intent="replan",
            change_request="重新规划行程",
            change_set={"operations": [{"operation": "full_replan"}]},
            top_suggestions=self.suggestions(),
            preference=None,
            done=True,
        ))

        result = agent.chat(TalkRequest(message="我要改计划"))

        self.assertEqual(result.intent, "replan")
        self.assertEqual(result.change_set.operations[0].operation, "full_replan")

    def test_chat_forces_full_replan_when_model_returns_advisory_chat(self) -> None:
        agent = self.build_agent(response(
            reply="深圳博物馆周一闭馆，请问您哪天出行？",
            intent="chat",
            change_request=None,
            change_set=None,
            top_suggestions=self.suggestions(),
            preference=None,
            done=False,
        ))

        result = agent.chat(TalkRequest(city="深圳", message="我要改计划"))

        self.assertEqual(result.intent, "replan")
        self.assertEqual(result.change_request, "重新规划当前行程")
        self.assertIsNotNone(result.change_set)
        self.assertEqual(result.change_set.operations[0].operation, "full_replan")
        self.assertTrue(result.done)

    def test_advisory_question_does_not_trigger_full_replan(self) -> None:
        agent = self.build_agent(response(
            reply="深圳博物馆通常周一闭馆。",
            intent="chat",
            change_request=None,
            change_set=None,
            top_suggestions=self.suggestions(),
            preference=None,
            done=False,
        ))

        result = agent.chat(TalkRequest(city="深圳", message="请问博物馆周一是否闭馆"))

        self.assertEqual(result.intent, "chat")
        self.assertIsNone(result.change_set)

    def test_negative_replan_phrase_does_not_trigger_full_replan(self) -> None:
        agent = self.build_agent(response(
            reply="好的，保持当前计划。",
            intent="chat",
            change_request=None,
            change_set=None,
            top_suggestions=self.suggestions(),
            preference=None,
            done=False,
        ))

        result = agent.chat(TalkRequest(message="我不想改计划"))

        self.assertEqual(result.intent, "chat")
        self.assertIsNone(result.change_set)

        agent = self.build_agent(
            response(
                reply="好的，删除第 0 天景点。",
                intent="replan",
                change_request="删除景点",
                change_set={"operations": [{
                    "operation": "delete_attraction",
                    "selector": {"day_index": -1},
                }]},
                top_suggestions=self.suggestions(),
                preference=None,
                done=True,
            ),
            [response(top_suggestions=self.suggestions())],
        )

        result = agent.chat(TalkRequest(message="删除第 0 天景点"))

        self.assertTrue(result.success)
        self.assertEqual(result.intent, "chat")
        self.assertIsNone(result.change_set)

    def test_chat_model_and_suggestion_failures_return_safe_response(self) -> None:
        class RaisingSuggestionAgent:
            def run(self, _prompt: str) -> str:
                raise RuntimeError("LLM unavailable")

        agent = object.__new__(TalkAgent)
        agent.agent = FakeDialogueAgent(["这不是 JSON 格式的模型响应"])
        agent.suggestion_agent = RaisingSuggestionAgent()

        result = agent.chat(TalkRequest(city="深圳", message="把行程改一下"))

        self.assertTrue(result.success)
        self.assertEqual(result.intent, "replan")
        self.assertIsNotNone(result.change_set)
        self.assertEqual(result.change_set.operations[0].operation, "full_replan")
        self.assertEqual(result.top_suggestions, [])


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证 TalkAgent 的对话、重规划和安全降级行为。")
