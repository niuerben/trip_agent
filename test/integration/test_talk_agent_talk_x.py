"""真实 TalkAgent.talk 连续上下文评测。"""

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
from backend.app.models.schemas import TalkMessage, TalkRequest


TALK_AGENT_TALK_CASES = [
    ("turn_01", "规划深圳三日游。"),
    ("turn_02", "节奏希望轻松一些，每天不要安排太多景点。"),
    ("turn_03", "第 2 天一定要安排深圳技术大学校园。"),
    # ("turn_04", "我喜欢本地美食，但不吃辣。"),
    # ("turn_05", "住宿选经济型酒店，靠近公共交通。"),
    # ("turn_06", "全程尽量坐地铁和公交，不想打车。"),
    # ("turn_07", "再增加一处海边或公园类自然景点。"),
    # ("turn_08", "两个人出行，每人每天餐饮预算控制在 150 元内。"),
    # ("turn_09", "第三天上午不要排太早，下午预留返程时间。"),
    # ("turn_10", "请根据前面的所有要求给出最终行程。"),
]

RESULTS_DIR = Path(__file__).resolve().parent / "results"
JSONL_RESULT_FILE = RESULTS_DIR / "talk_agent_talk_real_results.jsonl"
TEXT_RESULT_FILE = RESULTS_DIR / "talk_agent_talk_real_results.txt"


class RecordingPlanAgent:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.calls: list[tuple[str, str]] = []

    @property
    def prompt(self) -> str:
        return str(self.delegate.prompt)

    def plan(self, requirement_prompt: str, preference_prompt: str) -> Any:
        self.calls.append((requirement_prompt, preference_prompt))
        return self.delegate.plan(requirement_prompt, preference_prompt)


def build_request(
    message: str,
    messages: list[TalkMessage],
    plan_context: str,
) -> TalkRequest:
    return TalkRequest(
        city="深圳",
        plan_context=plan_context,
        messages=list(messages),
        message=message,
    )


def write_record(jsonl_output: Any, text_output: Any, record: dict[str, Any]) -> None:
    jsonl_output.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    jsonl_output.flush()
    text_output.write(
        f"Case: {record['id']}\n"
        f"Message: {record['request']['message']}\n"
        f"Passed: {record['passed']}\n"
        f"Error: {record['error']}\n"
        f"Duration(ms): {record['duration_ms']}\n"
        f"Iterations: {record['iterations']}\n\n"
        "Context Messages:\n"
        f"{json.dumps(record['context_messages'], ensure_ascii=False, indent=2)}\n\n"
        "Requirement Prompt Passed to PlanAgent:\n"
        f"{record['requirement_prompt']}\n\n"
        "Preference Prompt Passed to PlanAgent:\n"
        f"{record['preference_prompt']}\n\n"
        "Plan Response:\n"
        f"{json.dumps(record['response'], ensure_ascii=False, indent=2, default=str)}\n\n"
        "Loop Prompt:\n"
        f"{record['loop_prompt']}\n"
        + "=" * 80
        + "\n\n"
    )
    text_output.flush()


class TalkAgentTalkRealTest(unittest.TestCase):
    def test_ten_real_talk_calls_accumulate_context_and_are_recorded(self) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        history: list[TalkMessage] = []
        plan_context = "当前正在逐步收集深圳三日游的行程约束。"

        with (
            JSONL_RESULT_FILE.open("w", encoding="utf-8") as jsonl_output,
            TEXT_RESULT_FILE.open("w", encoding="utf-8") as text_output,
        ):
            try:
                agent = TalkAgent()
                recording_plan_agent = RecordingPlanAgent(agent.plan_agent)
                agent.plan_agent = recording_plan_agent
            except Exception as initialization_error:
                for case_id, message in TALK_AGENT_TALK_CASES:
                    request = build_request(message, history, plan_context)
                    write_record(jsonl_output, text_output, {
                        "id": case_id,
                        "request": request.model_dump(mode="json"),
                        "context_messages": [item.model_dump(mode="json") for item in history],
                        "requirement_prompt": "",
                        "preference_prompt": "",
                        "response": None,
                        "loop_prompt": "",
                        "iterations": 0,
                        "passed": False,
                        "error": f"{type(initialization_error).__name__}: {initialization_error}",
                        "duration_ms": 0,
                    })
                    history.extend([
                        TalkMessage(role="user", content=message),
                        TalkMessage(role="assistant", content="上一轮规划入口初始化失败。"),
                    ])
            else:
                for case_id, message in TALK_AGENT_TALK_CASES:
                    request = build_request(message, history, plan_context)
                    context_messages = [item.model_dump(mode="json") for item in history]
                    started = time.perf_counter()
                    try:
                        response = agent.talk(request)
                        requirement_prompt, passed_preference_prompt = recording_plan_agent.calls[-1]
                        loop_prompt = recording_plan_agent.prompt
                        passed = bool(response.get("passed", False)) if isinstance(response, dict) else False
                        error_message = response.get("error") if isinstance(response, dict) else "响应不是字典"
                    except Exception as caught_error:
                        response = None
                        requirement_prompt = ""
                        passed_preference_prompt = ""
                        loop_prompt = recording_plan_agent.prompt
                        passed = False
                        error_message = f"{type(caught_error).__name__}: {caught_error}"

                    record = {
                        "id": case_id,
                        "request": request.model_dump(mode="json"),
                        "context_messages": context_messages,
                        "requirement_prompt": requirement_prompt,
                        "preference_prompt": passed_preference_prompt,
                        "response": response,
                        "loop_prompt": loop_prompt,
                        "iterations": loop_prompt.count("Think:"),
                        "passed": passed,
                        "error": error_message,
                        "duration_ms": round((time.perf_counter() - started) * 1000),
                    }
                    write_record(jsonl_output, text_output, record)
                    history.extend([
                        TalkMessage(role="user", content=message),
                        TalkMessage(role="assistant", content=f"已处理第 {case_id} 轮约束。"),
                    ])
                    plan_context = "已确认的用户对话：" + "；".join(
                        item.content for item in history if item.role == "user"
                    )

        self.assertEqual(len(TALK_AGENT_TALK_CASES), len(JSONL_RESULT_FILE.read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    unittest.main()
