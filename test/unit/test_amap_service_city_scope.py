"""高德区县请求的父级城市与 adcode 解析测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.services.trip_planning_service import _is_district_adcode
from backend.app.services.amap_service import AmapService, _get_city_geocode_cached


class _Response:
    def __init__(self, address: str):
        self.address = address

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        results = {
            "广州越秀": {
                "location": "113.266835,23.128537",
                "adcode": "440104",
                "province": "广东省",
                "city": "广州市",
                "district": "越秀区",
            },
            "坪山": {
                "location": "114.350844,22.708884",
                "adcode": "440310",
                "province": "广东省",
                "city": "深圳市",
                "district": "坪山区",
            },
            "深圳坪山": {
                "location": "114.350844,22.708884",
                "adcode": "440310",
                "province": "广东省",
                "city": "深圳市",
                "district": "坪山区",
            },
            "虎门": {
                "location": "113.673034,22.814887",
                "adcode": "441900",
                "province": "广东省",
                "city": "东莞市",
                "district": "虎门镇",
            },
            "北京朝阳": {
                "location": "116.443108,39.921470",
                "adcode": "110105",
                "province": "北京市",
                "city": [],
                "district": "朝阳区",
            },
        }
        item = results.get(self.address)
        if item is None:
            raise AssertionError(f"未配置地址 {self.address!r} 的高德 geocode fixture")
        return {"status": "1", "geocodes": [item]}


class AmapServiceCityScopeTest(unittest.TestCase):
    def tearDown(self) -> None:
        _get_city_geocode_cached.cache_clear()

    def test_municipality_uses_province_when_city_is_empty(self) -> None:
        service = object.__new__(AmapService)
        service.api_key = "test-key"
        service.timeout = (1, 1)
        _get_city_geocode_cached.cache_clear()

        def geocode_response(_url, *, params, **_kwargs):
            return _Response(params.get("address", ""))

        with patch("backend.app.services.amap_service.requests.get", side_effect=geocode_response):
            self.assertEqual(service.get_poi_search_city("北京朝阳"), "北京市")

    def test_empty_city_returns_empty_without_network(self) -> None:
        service = object.__new__(AmapService)
        with patch("backend.app.services.amap_service.requests.get") as request:
            self.assertEqual(service.get_poi_search_city("  "), "")
        request.assert_not_called()



if __name__ == "__main__":
    unittest.main()
