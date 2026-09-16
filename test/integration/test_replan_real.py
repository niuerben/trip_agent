"""真实餐饮 replan 链路测试。

该测试不会替换 LLM、高德或规划服务，只允许在真实环境中显式运行：

    $env:RUN_REAL_SERVICE_TESTS = "1"
    python -m unittest test.integration.test_replan_real -v

需要 backend/.env 中配置真实的 LLM_API_KEY/LLM_BASE_URL 和 AMAP_API_KEY。
测试会实际调用模型与高德接口，耗时和费用取决于当前配置。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from test._gates import require_real_service_tests

from backend.app.agents.talk_agent import TalkAgent
from backend.app.config import get_settings
from backend.app.models.schemas import Preference, TalkRequest, TripRequest
from backend.app.services.trip_planning_service import TripPlanningService


class RealReplanIntegrationTest(unittest.TestCase):
    """验证真实 LLM → ChangeSet → 真实餐饮替换执行链路。"""

    @classmethod
    def setUpClass(cls) -> None:
        require_real_service_tests("真实 replan 集成测试")
        settings = get_settings()
        if not (settings.llm_api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")):
            raise unittest.SkipTest("未配置真实 LLM_API_KEY/OPENAI_API_KEY")
        if not settings.amap_api_key and not (
            os.getenv("AMAP_API_KEY") or os.getenv("AMAP_MAPS_API_KEY")
        ):
            raise unittest.SkipTest("未配置真实 AMAP_API_KEY")

    def test_real_talk_changeset_replans_current_meal(self) -> None:
        city = os.getenv("REAL_REPLAN_CITY", "广州")
        initial_request = TripRequest(
            city=city,
            start_date="2026-10-12",
            end_date="2026-10-13",
            travel_days=2,
            transportation="公共交通",
            accommodation="经济型酒店",
            preferences=["美食", "城市文化"],
            free_text_input="安排真实、可执行的两日城市行程，餐饮优先选择真实餐厅。",
        )

        planner = TripPlanningService()
        current_plan = planner.plan_trip(
            initial_request,
            Preference(prompt="两天城市旅行，关注真实餐饮和城市文化。"),
        )
        self.assertEqual(len(current_plan.days), initial_request.travel_days)
        self.assertTrue(any(day.meals for day in current_plan.days), "初始真实行程没有餐饮节点")

        first_day = current_plan.days[0]
        original_meal = next(
            (meal for meal in first_day.meals if meal.type == "lunch"),
            first_day.meals[0],
        )
        plan_context = json.dumps(
            current_plan.model_dump(mode="json"),
            ensure_ascii=False,
        )

        talk_agent = TalkAgent()
        talk_response = talk_agent.chat(TalkRequest(
            city=city,
            plan_context=plan_context,
            preference=Preference(prompt="保留城市文化，同时希望午餐换成火锅。"),
            messages=[],
            message=f"把第1天的午餐（{original_meal.name}）换成火锅。",
        ))

        self.assertEqual(talk_response.intent, "replan")
        self.assertIsNotNone(talk_response.change_set)
        self.assertIsNotNone(talk_response.change_request)
        self.assertTrue(talk_response.change_set.operations)
        operation = talk_response.change_set.operations[0]
        self.assertEqual(operation.operation, "replace_meal")
        target = operation.target
        self.assertIsNotNone(target)
        keywords = (target.semantic if target else "") or (target.name if target else "")
        self.assertIn("火锅", keywords)
        self.assertNotIn("非面", keywords)
        self.assertNotIn("not noodle", keywords.lower())

        replan_request = initial_request.model_copy(deep=True)
        replan_request.preference = talk_response.preference or Preference(
            prompt="保留城市文化，同时希望午餐换成火锅。"
        )
        replan_request.current_plan = current_plan.model_dump(mode="json")
        replan_request.change_request = talk_response.change_request
        replan_request.change_set = talk_response.change_set

        replanned = planner.plan_trip(replan_request, replan_request.preference)
        replanned_meal = next(
            (
                meal
                for meal in replanned.days[0].meals
                if meal.type == original_meal.type
            ),
            None,
        )

        self.assertIsNotNone(replanned_meal, "replan 后找不到原餐段")
        self.assertNotEqual(replanned_meal.name, original_meal.name)
        self.assertTrue(replanned_meal.name)
        self.assertTrue(replanned_meal.address)
        self.assertIsNotNone(replanned_meal.location)
        self.assertTrue(replanned_meal.poi_id)


if __name__ == "__main__":
    unittest.main()
