"""真实 PlanAgent.talk 意图识别评测。

需要真实 LLM 配置，且必须显式设置 RUN_REAL_SERVICE_TESTS=1 才会运行；
每组结果独立落盘，避免单个模型失败丢失已经完成的评测记录。
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.plan_agent import PlanAgent, build_talk_prompt
from backend.app.models.schemas import Preference, TalkRequest
from test._gates import require_real_service_tests, test_artifact_dir


TALK_CASES = [
    ("chat-advice", "深圳", "推荐适合慢节奏旅行的大学校园", "chat", None),
    # ("chat-food", "广州", "带孩子去旅行有哪些饮食建议", "chat", None),
    # ("chat-preference", "杭州", "我不想早起，也不吃辣", "chat", None),
    # ("delete", "深圳", "把寺庙景点删掉", "replan", "delete_attraction"),
    # ("replace", "深圳", "把马峦山改成大学", "replan", "replace_attraction"),
    # ("add", "深圳", "第2天加深圳技术大学", "replan", "add_attraction"),
    # ("update-dates", "成都", "改到10月1日至10月3日出发", "replan", "update_dates"),
    # ("full-replan", "重庆", "我要改计划", "replan", "full_replan"),
    # ("move", "西安", "把第2天的博物馆调到第1天下午", "replan", None),
    # ("budget-question", "青岛", "预算有限时住哪里方便", "chat", None),
]


def write_record(jsonl_output: Any, text_output: Any, record: dict[str, Any]) -> None:
    jsonl_output.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    jsonl_output.flush()
    text_output.write(
        f"Case: {record['case_id']}\n"
        f"Expected intent: {record['expected_intent']}\n"
        f"Passed: {record['passed']}\n"
        f"Error: {record['error']}\n"
        f"Duration(ms): {record['duration_ms']}\n\n"
        "Response:\n"
        f"{json.dumps(record['response'], ensure_ascii=False, indent=2, default=str)}\n\n"
        "Loop Prompt:\n"
        f"{record['loop_prompt']}\n"
        + "=" * 80
        + "\n\n"
    )
    text_output.flush()


class PlanAgentTalkRealTest(unittest.TestCase):
    def setUp(self) -> None:
        require_real_service_tests("真实 LLM 意图识别评测")

    def test_real_talk_calls_are_recorded_independently(self) -> None:
        results_dir = test_artifact_dir()
        results_dir.mkdir(parents=True, exist_ok=True)
        jsonl_result_file = results_dir / "plan_agent_talk_real_results.jsonl"
        text_result_file = results_dir / "plan_agent_talk_real_results.txt"
        with (
            jsonl_result_file.open("w", encoding="utf-8") as jsonl_output,
            text_result_file.open("w", encoding="utf-8") as text_output,
        ):
            try:
                agent = PlanAgent()
            except Exception as error:
                for case_id, city, message, expected_intent, expected_operation in TALK_CASES:
                    request = TalkRequest(city=city, message=message)
                    write_record(jsonl_output, text_output, {
                        "case_id": case_id,
                        "request": request.model_dump(mode="json"),
                        "expected_intent": expected_intent,
                        "expected_operation": expected_operation,
                        "response": None,
                        "loop_prompt": "",
                        "passed": False,
                        "error": f"{type(error).__name__}: {error}",
                        "duration_ms": 0,
                    })
            else:
                for case_id, city, message, expected_intent, expected_operation in TALK_CASES:
                    request = TalkRequest(
                        city=city,
                        preference=Preference(prompt="偏好慢节奏和本地美食"),
                        message=message,
                    )
                    prompt = build_talk_prompt(request)
                    started = time.perf_counter()
                    try:
                        response = agent.talk(request)
                        operation = (
                            response.change_set.operations[0].operation
                            if response.change_set and response.change_set.operations
                            else None
                        )
                        passed = response.intent == expected_intent and (
                            expected_operation is None or operation == expected_operation
                        )
                        error = None if passed else (
                            f"expected intent={expected_intent}, operation={expected_operation}; "
                            f"actual intent={response.intent}, operation={operation}"
                        )
                        response_data: Any = response.model_dump(mode="json")
                    except Exception as error:
                        passed = False
                        response_data = None
                        error = f"{type(error).__name__}: {error}"
                    write_record(jsonl_output, text_output, {
                        "case_id": case_id,
                        "request": request.model_dump(mode="json"),
                        "expected_intent": expected_intent,
                        "expected_operation": expected_operation,
                        "response": response_data,
                        "loop_prompt": prompt,
                        "passed": passed,
                        "error": error,
                        "duration_ms": round((time.perf_counter() - started) * 1000),
                    })

        records = jsonl_result_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(TALK_CASES), len(records))


if __name__ == "__main__":
    unittest.main()
