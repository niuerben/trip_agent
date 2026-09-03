"""旅行计划仅显示旅行日期内天气的回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.services.trip_planning_service import TripPlanningService
from backend.app.models.schemas import Location, TripRequest, WeatherInfo


def request() -> TripRequest:
    return TripRequest(
        city="深圳坪山",
        start_date="2026-07-27",
        end_date="2026-07-29",
        travel_days=3,
        transportation="公共交通",
        accommodation="经济型酒店",
    )


class TravelWeatherDateTest(unittest.TestCase):
    def test_filters_out_today_and_keeps_only_trip_days(self) -> None:
        forecast = [
            WeatherInfo(date="2026-07-25", day_weather="晴"),
            WeatherInfo(date="2026-07-26", day_weather="多云"),
            WeatherInfo(date="2026-07-27", day_weather="小雨"),
            WeatherInfo(date="2026-07-28", day_weather="阴"),
        ]

        result = TripPlanningService._weather_for_travel_dates(forecast, request())

        self.assertEqual([item.date for item in result], ["2026-07-27", "2026-07-28"])

    def test_does_not_relabel_out_of_window_forecast(self) -> None:
        forecast = [WeatherInfo(date="2026-07-25", day_weather="晴")]

        result = TripPlanningService._weather_for_travel_dates(forecast, request())

        self.assertEqual(result, [])

    def test_only_queries_the_missing_travel_date(self) -> None:
        class FakeWeatherService:
            def __init__(self) -> None:
                self.queried_dates = []

            def get_weather_for_date(self, city, target_date, location=None):
                self.queried_dates.append(target_date)
                return WeatherInfo(date=target_date, day_weather="雷雨", source="Open-Meteo")

        service = FakeWeatherService()
        forecast = [
            WeatherInfo(date="2026-07-27", day_weather="小雨"),
            WeatherInfo(date="2026-07-28", day_weather="阴"),
        ]
        with patch(
            "backend.app.services.amap_service.get_amap_service",
            return_value=service,
        ):
            result = TripPlanningService._complete_weather_for_travel_dates(
                forecast,
                request(),
                Location(longitude=114.4, latitude=22.7),
            )

        self.assertEqual(service.queried_dates, ["2026-07-29"])
        self.assertEqual([item.date for item in result], [
            "2026-07-27", "2026-07-28", "2026-07-29",
        ])


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证天气只保留并补齐实际旅行日期。")
