"""同日景点应按地理邻近顺序排列，避免无意义往返。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.services.trip_planning_service import TripPlanningService
from backend.app.models.schemas import Attraction, DayPlan, Location, Meal, TripPlan


class RouteOrderingTest(unittest.TestCase):
    def test_attractions_start_with_the_one_closest_to_breakfast(self) -> None:
        plan = TripPlan(
            city="测试城市",
            start_date="2026-07-27",
            end_date="2026-07-27",
            weather_info=[],
            overall_suggestions="测试",
            days=[DayPlan(
                date="2026-07-27",
                day_index=0,
                description="测试",
                transportation="公共交通",
                accommodation="经济型酒店",
                meals=[Meal(
                    type="breakfast", name="早餐", address="起点", description="",
                    location=Location(longitude=114.000, latitude=22.000),
                )],
                attractions=[
                    Attraction(name="远处景点", address="", description="", visit_duration=60,
                               location=Location(longitude=114.100, latitude=22.000)),
                    Attraction(name="近处景点", address="", description="", visit_duration=60,
                               location=Location(longitude=114.010, latitude=22.000)),
                    Attraction(name="中间景点", address="", description="", visit_duration=60,
                               location=Location(longitude=114.050, latitude=22.000)),
                ],
            )],
        )

        TripPlanningService._order_day_attractions_by_proximity(plan)

        self.assertEqual(
            [item.name for item in plan.days[0].attractions],
            ["近处景点", "中间景点", "远处景点"],
        )


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证同日景点按地理距离就近排序。")
