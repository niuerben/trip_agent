"""规划交付审查日志测试。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# 该脚本只验证 JSONL 审查日志，不应依赖本机 PostgreSQL 驱动。
os.environ["DATABASE_URL"] = ""

from backend.app.api.routes.trip import _write_planner_review_log
from backend.app.models.schemas import Preference, TripPlan, TripRequest


class PlannerReviewLoggingTest(unittest.TestCase):
    def test_approved_plan_writes_full_delivery_details(self) -> None:
        request = TripRequest(
            city="深圳坪山",
            start_date="2026-07-27",
            end_date="2026-07-27",
            travel_days=1,
            transportation="公共交通",
            accommodation="经济型酒店",
            conversation_id="conversation-log-test",
            change_request="补齐早餐",
        )
        plan = TripPlan(
            city="深圳坪山",
            start_date="2026-07-27",
            end_date="2026-07-27",
            days=[],
            overall_suggestions="已通过校验",
        )

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "planner_reviews.log"
            with patch(
                "backend.app.api.routes.trip.get_settings",
                return_value=SimpleNamespace(planner_review_log_path=str(log_path)),
            ):
                _write_planner_review_log(
                    status="approved",
                    request=request,
                    preference=Preference(prompt="喜欢大学校园"),
                    preference_source="talk_agent.conversation",
                    plan=plan,
                )

            payload = json.loads(log_path.read_text(encoding="utf-8").strip())

        self.assertEqual(payload["event"], "planner_delivery_review")
        self.assertEqual(payload["reviewer"], "trip_plan_validator")
        self.assertEqual(payload["request"]["change_request"], "补齐早餐")
        self.assertEqual(payload["trip_plan"]["overall_suggestions"], "已通过校验")


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证规划审查结果和完整计划写入日志。")
