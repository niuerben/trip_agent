"""结构化 ChangeSet 白名单执行测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.trip_planner_agent import TripPlannerAgent
from backend.app.models.schemas import (
    Attraction,
    ChangeSet,
    DayPlan,
    Location,
    TripPlan,
    TripRequest,
)
from backend.app.services.trip_plan_validator import TripPlanValidationError, validate_trip_plan


UNIVERSITY = {
    "id": "B0FFK4HFDB",
    "name": "深圳技术大学",
    "address": "兰田路3002号",
    "location": "114.399831,22.700708",
    "type": "科教文化服务;学校;高等院校",
    "adcode": "440310",
}


def plan() -> TripPlan:
    return TripPlan(
        city="深圳坪山",
        start_date="2026-07-27",
        end_date="2026-07-27",
        overall_suggestions="",
        days=[DayPlan(
            date="2026-07-27",
            day_index=0,
            description="第一天",
            transportation="公共交通",
            accommodation="经济型酒店",
            meals=[],
            attractions=[
                Attraction(
                    name="大华兴寺",
                    address="东部华侨城",
                    location=Location(longitude=114.287369, latitude=22.625217),
                    visit_duration=120,
                    description="风景名胜;寺庙道观",
                ),
                Attraction(
                    name="马峦山郊野公园",
                    address="坪山区",
                    location=Location(longitude=114.3, latitude=22.6),
                    visit_duration=120,
                    description="自然风光",
                ),
            ],
        )],
    )


def request(change_set: ChangeSet) -> TripRequest:
    return TripRequest(
        city="深圳坪山",
        start_date="2026-07-27",
        end_date="2026-07-27",
        travel_days=1,
        transportation="公共交通",
        accommodation="经济型酒店",
        current_plan=plan().model_dump(),
        change_set=change_set,
    )


class ChangeSetExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = object.__new__(TripPlannerAgent)

    def test_delete_attraction_by_llm_semantic_selector(self) -> None:
        change_set = ChangeSet.model_validate({"operations": [{
            "operation": "delete_attraction",
            "selector": {"semantic": "寺庙"},
        }]})
        result, changes = self.planner._execute_change_set(
            plan(), change_set, request(change_set), [], "440310"
        )
        self.assertEqual([item.name for item in result.days[0].attractions], ["马峦山郊野公园"])
        self.assertIn("大华兴寺", changes[0])

    def test_replace_attraction_uses_real_poi(self) -> None:
        change_set = ChangeSet.model_validate({"operations": [{
            "operation": "replace_attraction",
            "selector": {"name": "马峦山"},
            "target": {"semantic": "大学"},
        }]})
        with patch.object(TripPlannerAgent, "_resolve_replacement_poi", return_value=UNIVERSITY):
            result, _ = self.planner._execute_change_set(
                plan(), change_set, request(change_set), [], "440310"
            )
        self.assertEqual(result.days[0].attractions[1].name, "深圳技术大学")
        self.assertEqual(result.days[0].attractions[1].poi_id, "B0FFK4HFDB")

    def test_add_attraction_uses_selected_day(self) -> None:
        change_set = ChangeSet.model_validate({"operations": [{
            "operation": "add_attraction",
            "selector": {"day_index": 0},
            "target": {"semantic": "大学"},
        }]})
        with patch.object(TripPlannerAgent, "_resolve_replacement_poi", return_value=UNIVERSITY):
            result, _ = self.planner._execute_change_set(
                plan(), change_set, request(change_set), [], "440310"
            )
        self.assertEqual(result.days[0].attractions[-1].name, "深圳技术大学")

    def test_update_day_only_accepts_allowlisted_fields(self) -> None:
        change_set = ChangeSet.model_validate({"operations": [{
            "operation": "update_day",
            "selector": {"day_index": 0},
            "fields": {"transportation": "步行", "unknown": "ignored"},
        }]})
        result, _ = self.planner._execute_change_set(
            plan(), change_set, request(change_set), [], "440310"
        )
        self.assertEqual(result.days[0].transportation, "步行")
        self.assertFalse(hasattr(result.days[0], "unknown"))

    def test_local_change_cannot_deliver_legacy_plan_without_meal_locations(self) -> None:
        change_set = ChangeSet.model_validate({"operations": [{
            "operation": "update_day",
            "selector": {"day_index": 0},
            "fields": {"transportation": "步行"},
        }]})

        with self.assertRaises(TripPlanValidationError):
            validate_trip_plan(
                plan(),
                request(change_set),
                require_enriched_locations=True,
            )

    def test_unexecutable_change_set_is_replanned_instead_of_returning_422(self) -> None:
        """餐饮修改的空 update_day 需转给 ReAct，而非宣称已修改后直接失败。"""
        invalid_change_set = ChangeSet.model_validate({"operations": [{
            "operation": "update_day",
            "selector": {},
            "fields": {},
        }]})
        trip_request = request(invalid_change_set)
        trip_request.change_request = "将第2天晚餐添加至计划"

        replanned = plan()
        replanned.days[0].description = "已根据用户要求重新安排"

        class FakeAmapService:
            def get_city_center(self, _city):
                return Location(longitude=114.35, latitude=22.68)

            def get_city_adcode(self, _city):
                return "440310"

            def get_weather(self, _city):
                return []

        class FakeReActAgent:
            def __init__(self, *, session, **_kwargs):
                self.session = session

            def run(self, _query):
                self.session.validated_plan = replanned
                return "Finish[validator_passed]"

        self.planner.llm = object()
        self.planner._retrieve_cached_pois = lambda *_args, **_kwargs: []
        self.planner._complete_weather_for_travel_dates = lambda *_args, **_kwargs: []
        self.planner._enrich_attraction_images = lambda value, **_kwargs: value

        with (
            patch("backend.app.agents.trip_planner_agent.get_settings", return_value=SimpleNamespace(
                district_geo_radius_km=30,
                city_geo_radius_km=80,
                planner_preload_poi_evidence=True,
                planner_preloaded_deterministic_plan=False,
            )),
            patch("backend.app.services.amap_service.get_amap_service", return_value=FakeAmapService()),
            patch("backend.app.agents.trip_planner_agent.ValidatedPlanningReActAgent", FakeReActAgent),
            patch("backend.app.agents.trip_planner_agent.validate_trip_plan"),
        ):
            result = self.planner.plan_trip(trip_request)

        self.assertEqual(result.days[0].description, "已根据用户要求重新安排")
        self.assertEqual(trip_request.change_set.operations[0].operation, "update_day")


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证结构化变更、真实 POI 替换和计划保留。")
