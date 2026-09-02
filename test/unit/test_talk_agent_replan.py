"""talk LLM 结构化 ChangeSet 解析测试。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.talk_agent import TalkAgent
from backend.app.models.schemas import TalkRequest


class TalkChangeSetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = object.__new__(TalkAgent)

    def parse(self, payload: dict):
        return self.agent._parse_reply(json.dumps(payload, ensure_ascii=False))

    def test_deletion_is_parsed_without_regular_expressions(self) -> None:
        result = self.parse({
            "reply": "正在移除寺庙景点。",
            "intent": "replan",
            "change_request": "移除寺庙景点",
            "change_set": {"operations": [{
                "operation": "delete_attraction",
                "selector": {"semantic": "寺庙"},
            }]},
            "preference": None,
            "done": True,
        })
        self.assertEqual(result["change_set"].operations[0].selector.semantic, "寺庙")

    def test_replacement_is_parsed_as_source_and_target(self) -> None:
        result = self.parse({
            "reply": "正在替换景点。",
            "intent": "replan",
            "change_request": "把马峦山改成大学",
            "change_set": {"operations": [{
                "operation": "replace_attraction",
                "selector": {"name": "马峦山"},
                "target": {"semantic": "大学"},
            }]},
            "done": True,
        })
        operation = result["change_set"].operations[0]
        self.assertEqual(operation.selector.name, "马峦山")
        self.assertEqual(operation.target.semantic, "大学")

    def test_chat_discards_change_set(self) -> None:
        result = self.parse({
            "reply": "深圳坪山有不少本地餐馆。",
            "intent": "chat",
            "change_request": None,
            "change_set": {"operations": [{"operation": "full_replan"}]},
            "done": False,
        })
        self.assertIsNone(result["change_set"])

    def test_top_suggestions_are_read_from_llm_memory_response(self) -> None:
        result = self.parse({
            "reply": "已记录你喜欢轻松的校园路线。",
            "intent": "chat",
            "change_request": None,
            "change_set": None,
            "top_suggestions": ["把第二天的大学行程放慢一些", "增加校园附近平价午餐", "替换一处自然风光景点"],
            "done": True,
        })
        self.assertEqual(result["top_suggestions"], [
            "把第二天的大学行程放慢一些", "增加校园附近平价午餐", "替换一处自然风光景点",
        ])

    def test_replan_without_change_set_fails_closed_as_chat(self) -> None:
        result = self.parse({
            "reply": "正在修改。",
            "intent": "replan",
            "change_request": "改计划",
            "change_set": None,
            "done": True,
        })
        self.assertEqual(result["intent"], "chat")
        self.assertIsNone(result["change_set"])

    def test_top_suggestion_parser_requires_exactly_three_unique_values(self) -> None:
        self.assertEqual(
            self.agent._parse_suggestions(json.dumps({
                "top_suggestions": ["保留大学", "增加校园餐饮", "把第二天放慢"],
            }, ensure_ascii=False)),
            ["保留大学", "增加校园餐饮", "把第二天放慢"],
        )
        self.assertEqual(
            self.agent._parse_suggestions('{"top_suggestions":["重复","重复"]}'),
            [],
        )

    def test_chat_generates_top3_when_main_reply_omits_them(self) -> None:
        class FakeAgent:
            def __init__(self, reply: str) -> None:
                self.reply = reply

            def run(self, _prompt: str) -> str:
                return self.reply

        agent = object.__new__(TalkAgent)
        agent.agent = FakeAgent(json.dumps({
            "reply": "可以，我来为你调整。",
            "intent": "chat",
            "change_request": None,
            "change_set": None,
            "done": True,
        }, ensure_ascii=False))
        agent.suggestion_agent = FakeAgent(json.dumps({
            "top_suggestions": ["增加一处美食", "把第二天放慢", "查看附近咖啡店"],
        }, ensure_ascii=False))

        result = agent.chat(TalkRequest(message="给我推荐坪山美食"))

        self.assertEqual(result.top_suggestions, ["增加一处美食", "把第二天放慢", "查看附近咖啡店"])


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证对话中的重规划意图和 ChangeSet 解析。")
