"""高德道路与公共交通几何解析测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.services.amap_service import AmapService


class RouteGeometryTest(unittest.TestCase):
    def test_driving_steps_become_road_polylines(self) -> None:
        segments = AmapService._extract_driving_geometry({
            "route": {"paths": [{"steps": [{"polyline": "114.0,22.0;114.1,22.1"}]}]},
        })
        self.assertEqual(segments, [{"kind": "road", "points": [[114.0, 22.0], [114.1, 22.1]]}])

    def test_transit_keeps_subway_and_walking_geometries(self) -> None:
        segments = AmapService._extract_transit_geometry({
            "route": {"transits": [{"segments": [{
                "walking": {"steps": [{"polyline": "114.0,22.0;114.01,22.01"}]},
                "bus": {"buslines": [{"name": "地铁14号线", "type": "地铁", "polyline": "114.01,22.01;114.1,22.1"}]},
            }]}]},
        })
        self.assertEqual([item["kind"] for item in segments], ["walk", "subway"])
        self.assertEqual(segments[1]["points"][-1], [114.1, 22.1])


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证道路和公共交通路线几何解析。")
