"""高德区县请求的父级城市与 adcode 解析测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.agents.trip_planner_agent import _is_district_adcode
from backend.app.services.amap_service import AmapService, _get_city_geocode_cached


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "status": "1",
            "geocodes": [{
                "location": "113.266835,23.128537",
                "adcode": "440104",
                "province": "广东省",
                "city": "广州市",
                "district": "越秀区",
            }],
        }


class AmapServiceCityScopeTest(unittest.TestCase):
    def tearDown(self) -> None:
        _get_city_geocode_cached.cache_clear()

    def test_district_query_uses_parent_city_for_poi_search(self) -> None:
        service = object.__new__(AmapService)
        service.api_key = "test-key"
        service.timeout = (1, 1)
        _get_city_geocode_cached.cache_clear()

        with patch("backend.app.services.amap_service.requests.get", return_value=_Response()):
            self.assertEqual(service.get_city_adcode("广州越秀"), "440104")
            self.assertEqual(service.get_poi_search_city("广州越秀"), "广州市")

        self.assertTrue(_is_district_adcode("440104"))
        self.assertFalse(_is_district_adcode("440100"))


if __name__ == "__main__":
    unittest.main()
