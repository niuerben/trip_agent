from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.talk_agent import TalkAgent
from backend.app.models.schemas import TalkMessage, TalkRequest


class FakeAgent:
    def run(self, _prompt: str) -> str:
        return json.dumps({
            "reply": "好的，已经按新日期调整顺序。",
            "intent": "chat",
            "change_set": None,
            "top_suggestions": ["继续调整", "查看天气", "导出行程"],
            "preference": None,
            "done": False,
        })


class DateSyncFallbackTest(unittest.TestCase):
    def test_confirmation_uses_prior_assistant_date_range(self) -> None:
        agent = object.__new__(TalkAgent)
        agent.agent = FakeAgent()
        agent.suggestion_agent = FakeAgent()
        result = agent.chat(TalkRequest(
            city="深圳",
            plan_context="深圳，行程日期：2026-09-01 至 2026-09-03；第1天：博物馆",
            messages=[TalkMessage(
                role="assistant",
                content="根据新日期（9月5日周六至9月7日周一）已调整顺序。",
            )],
            message="确认新日期后的行程安排",
        ))
        self.assertEqual(result.intent, "replan")
        operation = result.change_set.operations[0]
        self.assertEqual(operation.operation, "update_dates")
        self.assertEqual(operation.fields, {
            "start_date": "2026-09-05",
            "end_date": "2026-09-07",
        })


if __name__ == "__main__":
    unittest.main()
