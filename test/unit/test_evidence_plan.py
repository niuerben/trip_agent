"""完整 POI 证据应在不调用模型时生成合格的近邻行程。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.planning_react_agent import PlanningSession, PlanningToolset
from backend.app.agents.trip_planner_agent import TripPlannerAgent
from backend.app.models.schemas import Location, TripRequest
from backend.app.services.trip_plan_validator import collect_trip_plan_issues


class EvidencePlanTest(unittest.TestCase):
    def test_groups_unique_meals_into_short_daily_routes(self) -> None:
        request = TripRequest(
            city="测试城区",
            start_date="2026-07-27",
            end_date="2026-07-29",
            travel_days=3,
            transportation="公共交通",
            accommodation="经济型酒店",
            free_text_input="每餐人均不超过40元",
        )
        session = PlanningSession(
            request=request,
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode=None,
            amap_city="测试城区",
        )
        # 三个街区，每个街区都有三家餐厅和一个景点；输入顺序故意打乱。
        meals = [
            {
                "poi_id": f"meal-{district}-{index}",
                "name": f"餐厅{district}-{index}",
                "address": f"测试路{district}-{index}号",
                "location": f"{114.40 + district * 0.03 + index * 0.001},{22.70 + district * 0.01}",
                "cost": "35",
            }
            for district in range(3)
            for index in range(3)
        ]
        attractions = [
            {
                "poi_id": f"attraction-{district}",
                "name": f"景点{district}",
                "address": f"景点路{district}号",
                "location": f"{114.401 + district * 0.03},{22.701 + district * 0.01}",
                "type": "风景名胜",
            }
            for district in range(3)
        ]
        session.evidence_records = {
            "meal": {item["poi_id"]: item for item in reversed(meals)},
            "attraction": {item["poi_id"]: item for item in reversed(attractions)},
        }
        session.evidence_ids = {
            "meal": set(session.evidence_records["meal"]),
            "attraction": set(session.evidence_records["attraction"]),
        }

        plan = TripPlannerAgent._build_evidence_plan(request, session)

        self.assertIsNotNone(plan)
        self.assertEqual(len({meal.poi_id for day in plan.days for meal in day.meals}), 9)
        self.assertEqual(len({item.poi_id for day in plan.days for item in day.attractions}), 3)
        self.assertFalse(collect_trip_plan_issues(plan, request))
        result = PlanningToolset(session).validate_draft(plan.model_dump_json())
        self.assertIn('"passed": true', result)


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证真实 POI 的去重和每日近邻排程。")
