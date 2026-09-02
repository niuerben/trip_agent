"""真实 TalkAgent.chat 意图识别评测。

该模块需要真实 LLM 配置，只应作为集成评测运行；每组结果独立落盘，
避免单个模型失败丢失已经完成的评测记录。
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

from backend.app.agents.talk_agent import TalkAgent
from backend.app.models.schemas import Preference, TalkRequest


CHAT_CASES = [
    ("chat-advice", "深圳", "推荐适合慢节奏旅行的大学校园", "chat", None),
    # ("chat-food", "广州", "带孩子去旅行有哪些饮食建议", "chat", None),
    # ("chat-preference", "杭州", "我不想早起，也不吃辣", "chat", None),
    # ("delete", "深圳", "把寺庙景点删掉", "replan", "delete_attraction"),
    # ("replace", "深圳", "把马峦山改成大学", "replan", "replace_attraction"),
    # ("add", "深圳", "第2天加深圳技术大学", "replan", "add_attraction"),
    # ("update-day", "成都", "第1天交通改成步行", "replan", "update_day"),
    # ("full-replan", "重庆", "我要改计划", "replan", "full_replan"),
    # ("move", "西安", "把第2天的博物馆调到第1天下午", "replan", None),
    # ("budget-question", "青岛", "预算有限时住哪里方便", "chat", None),
]

RESULTS_DIR = Path(__file__).resolve().parent / "results"
JSONL_RESULT_FILE = RESULTS_DIR / "talk_agent_chat_real_results.jsonl"
TEXT_RESULT_FILE = RESULTS_DIR / "talk_agent_chat_real_results.txt"


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


class TalkAgentChatRealTest(unittest.TestCase):
    def test_ten_real_chat_calls_are_recorded_independently(self) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        with (
            JSONL_RESULT_FILE.open("w", encoding="utf-8") as jsonl_output,
            TEXT_RESULT_FILE.open("w", encoding="utf-8") as text_output,
        ):
            try:
                agent = TalkAgent()
            except Exception as error:
                for case_id, city, message, expected_intent, expected_operation in CHAT_CASES:
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
                for case_id, city, message, expected_intent, expected_operation in CHAT_CASES:
                    request = TalkRequest(
                        city=city,
                        preference=Preference(prompt="偏好慢节奏和本地美食"),
                        message=message,
                    )
                    prompt = agent._build_prompt(request)
                    started = time.perf_counter()
                    try:
                        response = agent.chat(request)
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

        records = JSONL_RESULT_FILE.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(CHAT_CASES), len(records))


if __name__ == "__main__":
    unittest.main()
