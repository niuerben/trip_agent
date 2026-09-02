"""规划与对话 Agent 的无外部服务集成测试。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.talk_agent import TalkAgent
from backend.app.services.trip_planning_service import TripPlanningService
from backend.app.models.schemas import (
    Attraction,
    ChangeSet,
    DayPlan,
    Location,
    Preference,
    TalkRequest,
    TripPlan,
    TripRequest,
)


def _request(**kwargs) -> TripRequest:
    return TripRequest(
        city="测试城区",
        start_date="2026-07-27",
        end_date="2026-07-27",
        travel_days=1,
        transportation="公共交通",
        accommodation="经济型酒店",
        **kwargs,
    )


def _plan() -> TripPlan:
    return TripPlan(
        city="测试城区",
        start_date="2026-07-27",
        end_date="2026-07-27",
        overall_suggestions="测试计划",
        days=[DayPlan(
            date="2026-07-27",
            day_index=0,
            description="校园路线",
            transportation="公共交通",
            accommodation="经济型酒店",
            attractions=[Attraction(
                name="测试大学",
                address="测试路1号",
                location=Location(longitude=114.4, latitude=22.7),
                visit_duration=120,
                description="校园",
                poi_id="A-1",
            )],
            meals=[],
        )],
    )


class TripPlanningServiceIntegrationTest(unittest.TestCase):
    def test_plan_trip_delivers_react_validated_response(self) -> None:
        request = _request()
        delivered = _plan()
        trace: list[tuple[str, object]] = []

        class FakeAmap:
            def get_city_center(self, city):
                trace.append(("city_center", city))
                return Location(longitude=114.4, latitude=22.7)

            def get_city_adcode(self, city):
                trace.append(("city_adcode", city))
                return "440300"

            def get_weather(self, city):
                trace.append(("weather", city))
                return []

        class FakeReAct:
            def __init__(self, *, llm, session):
                trace.append(("react_init", session))
                self.session = session

            def run(self, query):
                trace.append(("react_run", query))
                self.session.validated_plan = delivered.model_copy(deep=True)
                return self.session.validated_plan.model_dump_json()

        settings = SimpleNamespace(
            district_geo_radius_km=25,
            city_geo_radius_km=80,
            planner_preload_poi_evidence=False,
            planner_preloaded_deterministic_plan=False,
        )
        agent = object.__new__(TripPlanningService)
        agent.llm = object()
        with (
            patch("backend.app.services.trip_planning_service.get_settings", return_value=settings),
            patch("backend.app.services.amap_service.get_amap_service", return_value=FakeAmap()),
            patch.object(agent, "_retrieve_cached_pois", return_value=[]),
            patch("backend.app.services.trip_planning_service.ValidatedPlanningReActAgent", FakeReAct),
            patch.object(TripPlanningService, "_complete_weather_for_travel_dates", side_effect=lambda facts, *_: facts),
            patch.object(TripPlanningService, "_enrich_attraction_images", side_effect=lambda plan, **_: plan),
            patch("backend.app.services.trip_planning_service.validate_trip_plan") as validate,
        ):
            result = agent.plan_trip(request, Preference(prompt="偏好校园和轻松节奏"))

        self.assertEqual(result.city, request.city)
        self.assertEqual(len(result.days), 1)
        self.assertEqual(result.days[0].date, request.start_date)
        self.assertIn("react_init", [event for event, _ in trace])
        query = next(value for event, value in trace if event == "react_run")
        self.assertIn("偏好校园和轻松节奏", query)
        validate.assert_called()

    def test_talk_changeset_is_consumable_by_trip_planner(self) -> None:
        talk_agent = object.__new__(TalkAgent)

        class FakeDialogue:
            def run(self, _prompt: str) -> str:
                return json.dumps({
                    "reply": "我会移除校园景点。",
                    "intent": "replan",
                    "change_request": "移除校园景点",
                    "change_set": {"operations": [{
                        "operation": "delete_attraction",
                        "selector": {"semantic": "校园"},
                    }]},
                    "top_suggestions": ["增加公园", "放慢节奏", "补充午餐"],
                    "preference": {"prompt": "偏好轻松节奏"},
                    "done": True,
                }, ensure_ascii=False)

        talk_agent.agent = FakeDialogue()
        talk_agent.suggestion_agent = FakeDialogue()
        talk_response = talk_agent.chat(TalkRequest(
            city="测试城区",
            plan_context="第 1 天安排测试大学",
            message="移除校园景点",
        ))
        self.assertEqual(talk_response.intent, "replan")
        self.assertIsNotNone(talk_response.change_set)

        current = _plan()
        request = _request(
            preference=talk_response.preference,
            current_plan=current.model_dump(),
            change_request=talk_response.change_request,
            change_set=talk_response.change_set,
        )
        planner = object.__new__(TripPlanningService)
        planner.llm = object()
        settings = SimpleNamespace(district_geo_radius_km=25, city_geo_radius_km=80)
        with (
            patch("backend.app.services.trip_planning_service.get_settings", return_value=settings),
            patch("backend.app.services.amap_service.get_amap_service", return_value=SimpleNamespace(
                get_city_center=lambda _city: Location(longitude=114.4, latitude=22.7),
                get_city_adcode=lambda _city: "440300",
            )),
            patch.object(planner, "_retrieve_cached_pois", return_value=[]),
            patch("backend.app.services.trip_planning_service.validate_trip_plan"),
        ):
            result = planner.plan_trip(request)

        self.assertEqual(result.days[0].attractions, [])
        self.assertEqual(result.city, current.city)


if __name__ == "__main__":
    unittest.main()
