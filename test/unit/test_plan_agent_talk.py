"""PlanAgent 对话、结构化解析与安全降级行为测试。

意图识别由提示词驱动（LLM 决定 chat/replan），后端只做
JSON 解析、ChangeSet 校验与安全降级，本文件验证这些契约。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.plan_agent import PlanAgent
from backend.app.models.schemas import TalkMessage, TalkRequest


class FakeDialogueAgent:
    def __init__(self, replies: list[str]) -> None:
        self.replies = iter(replies)
        self.prompts: list[str] = []

    def run(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self.replies)


def response(**payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


class PlanAgentTalkTest(unittest.TestCase):
    def build_agent(self, main_reply: str, suggestion_replies: list[str] | None = None) -> PlanAgent:
        agent = object.__new__(PlanAgent)
        agent.agent = FakeDialogueAgent([main_reply])
        agent.suggestion_agent = FakeDialogueAgent(suggestion_replies or [])
        return agent

    @staticmethod
    def suggestions() -> list[str]:
        return ["安排在上午", "增加附近午餐", "减少一处景点"]

    def test_build_prompt_keeps_city_plan_preference_and_history_order(self) -> None:
        agent = object.__new__(PlanAgent)
        prompt = agent._build_prompt(TalkRequest(
            city="深圳",
            plan_context="第 1 天安排深圳技术大学",
            messages=[
                TalkMessage(role="user", content="我喜欢大学校园"),
                TalkMessage(role="assistant", content="我会优先安排校园路线"),
            ],
            message="第 2 天加一处公园",
        ))

        expected_fragments = [
            "当前旅行计划目的地: 深圳",
            "当前行程摘要（当前行程事实，仅以此为准解析‘第几天’、已有景点和住宿餐饮；不要把聊天历史中的建议当成已执行安排）: 第 1 天安排深圳技术大学",
            "用户: 我喜欢大学校园",
            "顾问: 我会优先安排校园路线",
            "用户: 第 2 天加一处公园",
        ]
        positions = [prompt.index(fragment) for fragment in expected_fragments]
        self.assertEqual(positions, sorted(positions))

    def test_talk_uses_model_suggestions_without_fallback(self) -> None:
        agent = self.build_agent(response(
            reply="可以安排校园与美食路线。",
            intent="chat",
            change_request=None,
            change_set=None,
            top_suggestions=self.suggestions(),
            preference=None,
            done=False,
        ))

        result = agent.talk(TalkRequest(city="深圳", message="推荐一个轻松路线"))

        self.assertEqual(result.intent, "chat")
        self.assertEqual(result.top_suggestions, self.suggestions())
        self.assertEqual(agent.suggestion_agent.prompts, [])

    def test_talk_generates_top3_when_main_reply_omits_them(self) -> None:
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

        result = agent.talk(TalkRequest(city="深圳", message="给我推荐坪山美食"))

        self.assertEqual(result.top_suggestions, ["增加一处美食", "把第二天放慢", "查看附近咖啡店"])
        self.assertEqual(len(agent.suggestion_agent.prompts), 1)
        self.assertIn("当前旅行计划目的地: 深圳", agent.suggestion_agent.prompts[0])

    def test_talk_builds_delete_attraction_changeset(self) -> None:
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

        result = agent.talk(TalkRequest(message="把寺庙景点删掉"))

        operation = result.change_set.operations[0]
        self.assertEqual(result.intent, "replan")
        self.assertEqual(operation.operation, "delete_attraction")
        self.assertEqual(operation.selector.semantic, "寺庙")

    def test_talk_builds_replace_attraction_changeset(self) -> None:
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

        result = agent.talk(TalkRequest(message="把马峦山改成大学"))

        operation = result.change_set.operations[0]
        self.assertEqual(operation.operation, "replace_attraction")
        self.assertEqual(operation.selector.name, "马峦山")
        self.assertEqual(operation.target.semantic, "大学")

    def test_talk_builds_add_attraction_changeset(self) -> None:
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

        result = agent.talk(TalkRequest(message="第 2 天加深圳技术大学"))

        operation = result.change_set.operations[0]
        self.assertEqual(operation.operation, "add_attraction")
        self.assertEqual(operation.selector.day_index, 1)
        self.assertEqual(operation.target.semantic, "深圳技术大学")

    def test_talk_builds_full_replan_changeset(self) -> None:
        agent = self.build_agent(response(
            reply="好的，我会重新规划整个行程。",
            intent="replan",
            change_request="重新规划行程",
            change_set={"operations": [{"operation": "full_replan"}]},
            top_suggestions=self.suggestions(),
            preference=None,
            done=True,
        ))

        result = agent.talk(TalkRequest(message="我要改计划"))

        self.assertEqual(result.intent, "replan")
        self.assertEqual(result.change_set.operations[0].operation, "full_replan")

    def test_update_dates_change_set_is_supported(self) -> None:
        agent = self.build_agent(response(
            reply="好的，我已调整出行日期。",
            intent="replan",
            change_request="调整出行日期",
            change_set={"operations": [{
                "operation": "update_dates",
                "fields": {"start_date": "2026-10-01", "end_date": "2026-10-03"},
            }]},
            top_suggestions=self.suggestions(),
            preference=None,
            done=True,
        ))

        result = agent.talk(TalkRequest(message="改到10月1日至10月3日"))

        operation = result.change_set.operations[0]
        self.assertEqual(result.intent, "replan")
        self.assertEqual(operation.operation, "update_dates")
        self.assertEqual(operation.fields["start_date"], "2026-10-01")

    def test_advisory_question_remains_chat(self) -> None:
        agent = self.build_agent(response(
            reply="深圳博物馆通常周一闭馆。",
            intent="chat",
            change_request=None,
            change_set=None,
            top_suggestions=self.suggestions(),
            preference=None,
            done=False,
        ))

        result = agent.talk(TalkRequest(city="深圳", message="请问博物馆周一是否闭馆"))

        self.assertEqual(result.intent, "chat")
        self.assertIsNone(result.change_set)

    def test_model_chat_intent_is_respected_for_replan_request(self) -> None:
        """意图识别交给 LLM：模型返回 chat 时后端不再强制 full_replan。"""
        agent = self.build_agent(response(
            reply="深圳博物馆周一闭馆，请问您哪天出行？",
            intent="chat",
            change_request=None,
            change_set=None,
            top_suggestions=self.suggestions(),
            preference=None,
            done=False,
        ))

        result = agent.talk(TalkRequest(city="深圳", message="我要改计划"))

        self.assertEqual(result.intent, "chat")
        self.assertIsNone(result.change_set)

    def test_invalid_changeset_degrades_to_chat_and_keeps_reply(self) -> None:
        agent = self.build_agent(
            response(
                reply="好的，删除第 0 天景点。",
                intent="replan",
                change_request="删除景点",
                change_set={"operations": [{
                    "operation": "delete_attraction",
                    "selector": {"day_index": -1},
                }]},
            ),
            [response(top_suggestions=self.suggestions())],
        )

        result = agent.talk(TalkRequest(message="删除第 0 天景点"))

        self.assertTrue(result.success)
        self.assertEqual(result.intent, "chat")
        self.assertIsNone(result.change_set)
        self.assertIn("删除第 0 天景点", result.reply)
        self.assertEqual(result.top_suggestions, self.suggestions())

    def test_replan_without_changeset_degrades_to_chat(self) -> None:
        agent = self.build_agent(
            response(
                reply="我来重新规划一下。",
                intent="replan",
                change_request="重新规划",
                change_set=None,
            ),
            [response(top_suggestions=self.suggestions())],
        )

        result = agent.talk(TalkRequest(message="重新规划"))

        self.assertEqual(result.intent, "chat")
        self.assertIsNone(result.change_set)
        self.assertEqual(result.reply, "我来重新规划一下。")

    def test_non_json_output_degrades_to_chat_and_fills_suggestions(self) -> None:
        agent = object.__new__(PlanAgent)
        agent.agent = FakeDialogueAgent(["这不是 JSON 格式的模型响应"])
        agent.suggestion_agent = FakeDialogueAgent(
            [response(top_suggestions=self.suggestions())]
        )

        result = agent.talk(TalkRequest(city="深圳", message="把行程改一下"))

        self.assertTrue(result.success)
        self.assertEqual(result.intent, "chat")
        self.assertIsNone(result.change_set)
        self.assertEqual(result.reply, "这不是 JSON 格式的模型响应")
        self.assertEqual(result.top_suggestions, self.suggestions())


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证 PlanAgent 的对话、结构化解析与安全降级行为。")
