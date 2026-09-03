"""TalkAgent.talk 连续上下文到 PlanAgent 输入的集成测试。"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.talk_agent import TalkAgent
from backend.app.models.schemas import Preference, TalkMessage, TalkRequest


TALK_AGENT_TALK_CASES = [
    ("turn_01", "规划深圳三日游。", "旅行三天，优先大学校园和自然风光。"),
    ("turn_02", "节奏希望轻松一些，每天不要安排太多景点。", "偏好慢节奏，每天最多两个主要景点。"),
    ("turn_03", "第 2 天一定要安排深圳技术大学校园。", "第 2 天安排深圳技术大学校园。"),
    ("turn_04", "我喜欢本地美食，但不吃辣。", "喜欢本地美食，饮食避免辛辣。"),
    ("turn_05", "住宿选经济型酒店，靠近公共交通。", "住宿选择靠近公共交通的经济型酒店。"),
    ("turn_06", "全程尽量坐地铁和公交，不想打车。", "优先地铁和公交，减少打车。"),
    ("turn_07", "再增加一处海边或公园类自然景点。", "增加一处海边或公园类自然景点。"),
    ("turn_08", "两个人出行，每人每天餐饮预算控制在 150 元内。", "两人出行，每人每天餐饮预算不超过 150 元。"),
    ("turn_09", "第三天上午不要排太早，下午预留返程时间。", "第三天上午晚些开始，下午预留返程时间。"),
    ("turn_10", "请根据前面的所有要求给出最终行程。", "最终行程必须满足此前全部约束。"),
]

RESULTS_DIR = Path(__file__).resolve().parent / "results"
JSONL_RESULT_FILE = RESULTS_DIR / "talk_agent_talk_context_results.jsonl"
TEXT_RESULT_FILE = RESULTS_DIR / "talk_agent_talk_context_results.txt"


class CapturingPlanAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def plan(self, requirement_prompt: str, preference_prompt: str) -> dict[str, bool]:
        self.calls.append((requirement_prompt, preference_prompt))
        return {"passed": True, "captured": True}


def build_request(
    message: str,
    preference_prompt: str,
    messages: list[TalkMessage],
    plan_context: str,
) -> TalkRequest:
    return TalkRequest(
        city="深圳",
        plan_context=plan_context,
        preference=Preference(prompt=preference_prompt),
        messages=list(messages),
        message=message,
    )


def write_record(jsonl_output: Any, text_output: Any, record: dict[str, Any]) -> None:
    jsonl_output.write(json.dumps(record, ensure_ascii=False) + "\n")
    jsonl_output.flush()
    text_output.write(
        f"Case: {record['id']}\n"
        f"Message: {record['request']['message']}\n"
        f"Passed: {record['passed']}\n"
        f"Error: {record['error']}\n"
        f"Duration(ms): {record['duration_ms']}\n\n"
        "Context Messages:\n"
        f"{json.dumps(record['context_messages'], ensure_ascii=False, indent=2)}\n\n"
        "Requirement Prompt Passed to PlanAgent:\n"
        f"{record['requirement_prompt']}\n\n"
        "Preference Prompt Passed to PlanAgent:\n"
        f"{record['preference_prompt']}\n"
        + "=" * 80
        + "\n\n"
    )
    text_output.flush()


class TalkAgentTalkContextTest(unittest.TestCase):
    def test_ten_talk_calls_accumulate_context_and_capture_plan_inputs(self) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        agent = object.__new__(TalkAgent)
        plan_agent = CapturingPlanAgent()
        agent.plan_agent = plan_agent
        history: list[TalkMessage] = []
        preference_parts: list[str] = []
        plan_context = "当前正在逐步收集深圳三日游的行程约束。"

        with (
            JSONL_RESULT_FILE.open("w", encoding="utf-8") as jsonl_output,
            TEXT_RESULT_FILE.open("w", encoding="utf-8") as text_output,
        ):
            for case_id, message, preference_update in TALK_AGENT_TALK_CASES:
                preference_parts.append(preference_update)
                preference_prompt = "；".join(preference_parts)
                request = build_request(message, preference_prompt, history, plan_context)
                context_messages = [item.model_dump(mode="json") for item in history]
                started = time.perf_counter()
                try:
                    response = agent.talk(request)
                    requirement_prompt, passed_preference_prompt = plan_agent.calls[-1]
                    passed = response == {"passed": True, "captured": True}
                    error = None if passed else "PlanAgent 捕获器返回了意外响应"
                except Exception as caught_error:
                    requirement_prompt = ""
                    passed_preference_prompt = preference_prompt
                    passed = False
                    error = f"{type(caught_error).__name__}: {caught_error}"

                record = {
                    "id": case_id,
                    "request": request.model_dump(mode="json"),
                    "context_messages": context_messages,
                    "requirement_prompt": requirement_prompt,
                    "preference_prompt": passed_preference_prompt,
                    "passed": passed,
                    "error": error,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                }
                write_record(jsonl_output, text_output, record)
                history.extend([
                    TalkMessage(role="user", content=message),
                    TalkMessage(role="assistant", content=f"已将第 {case_id} 轮约束传给规划 Agent。"),
                ])
                plan_context = "已确认约束：" + "；".join(preference_parts)

        self.assertEqual(len(TALK_AGENT_TALK_CASES), len(plan_agent.calls))
        self.assertEqual(len(TALK_AGENT_TALK_CASES), len(JSONL_RESULT_FILE.read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    unittest.main()
