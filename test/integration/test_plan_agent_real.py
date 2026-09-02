"""真实 LLM 规划样本；显式开启后运行，不属于单元测试。"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

from hello_agents import ReActAgent

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from test._gates import require_real_service_tests, test_artifact_dir
from backend.app.agents.plan_agent import plan


PLAN_AGENT_CASES = [
    ("规划陆丰三日游", "偏好美食和自然风光"),
    ("规划北京周末行程", "不喜欢历史文化，喜欢现代文明"),
    # ("安排上海亲子旅行", "两位成人和一个孩子"),
    # ("设计广州美食路线", "预算经济，避开辛辣"),
    # ("规划杭州两日游", "希望多安排自然风光"),
    # ("安排成都旅行", "偏好咖啡、街区和慢节奏"),
    # ("规划西安历史路线", "重点参观博物馆"),
    # ("设计厦门海边行程", "喜欢拍照，不安排早起"),
    # ("安排重庆城市漫游", "使用公共交通，少爬坡"),
    # ("规划青岛夏日旅行", "偏好海鲜和轻松路线"),
]

RESULTS_DIR = test_artifact_dir() / "plan_agent_real"
RESULT_FILE = RESULTS_DIR / "results.jsonl"
TEXT_RESULT_FILE = RESULTS_DIR / "results.txt"


class PlanAgentRealTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        require_real_service_tests("This test calls the real LLM")

    def test_each_input_is_recorded_independently(self) -> None:
        RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with (
            RESULT_FILE.open("w", encoding="utf-8") as output,
            TEXT_RESULT_FILE.open("w", encoding="utf-8") as text_output,
        ):
            cnt = 0
            for requirement_prompt, preference_prompt in PLAN_AGENT_CASES:
                started = time.perf_counter()
                record: dict[str, object] = {
                    "requirement_prompt": requirement_prompt,
                    "preference_prompt": preference_prompt,
                }
                try:
                    case_started = time.perf_counter()
                    response = plan(requirement_prompt, preference_prompt)

                    loop_prompt = str(response.get("loop_prompt", "")) if isinstance(response, dict) else ""
                    record.update({
                        "passed": bool(response.get("passed", False)) if isinstance(response, dict) else True,
                        "error": response.get("error") if isinstance(response, dict) else None,
                        "model_response": str(response),
                        "loop_prompt": loop_prompt,
                        "iterations": loop_prompt.count("Think:"),
                    })
                    cnt += 1
                    print(f'第{cnt}个样本耗时: {round((time.perf_counter() - case_started) * 1000)} ms')

                except Exception as error:  # preserve later samples when one call fails
                    record.update({
                        "passed": False,
                        "error": f"{type(error).__name__}: {error}",
                        "model_response": None,
                        "loop_prompt": "",
                        "iterations": 0,
                    })
                record["duration_ms"] = round((time.perf_counter() - started) * 1000)
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                text_output.write(
                    f"Requirement: {record['requirement_prompt']}\n"
                    f"Preference: {record['preference_prompt']}\n"
                    f"Passed: {record['passed']}\n"
                    f"Error: {record['error']}\n"
                    f"Duration(ms): {record['duration_ms']}\n"
                    f"Iterations: {record['iterations']}\n\n"
                    "Loop Prompt:\n"
                    f"{record['loop_prompt']}\n\n"
                    "Model Response:\n"
                    f"{record['model_response']}\n"
                    + "=" * 80
                    + "\n\n"
                )
                text_output.flush()

        records = [json.loads(line) for line in RESULT_FILE.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(PLAN_AGENT_CASES), len(records))
        self.assertTrue(TEXT_RESULT_FILE.exists())
        failures = [
            f"{record['requirement_prompt']}: {record['error']}"
            for record in records
            if not record["passed"]
        ]
        self.assertEqual([], failures, "\\n".join(failures))


if __name__ == "__main__":
    unittest.main()
