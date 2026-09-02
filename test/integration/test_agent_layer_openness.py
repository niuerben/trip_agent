"""临时开放性测试：观察 TripPlanningService 是否只是空转代理层。

该测试故意不写入 README。它用源码契约记录规划入口必须承担的编排职责，
便于后续决定是否合并两层 Agent 或继续保留领域入口。
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.services.trip_planning_service import TripPlanningService


class AgentLayerOpennessTest(unittest.TestCase):
    def test_trip_planner_layer_has_real_orchestration_points(self) -> None:
        source = inspect.getsource(TripPlanningService.plan_trip)
        responsibilities = {
            "context_retrieval": "_retrieve_cached_pois" in source,
            "session_construction": "PlanningSession" in source,
            "toolset_preload": "PlanningToolset" in source,
            "react_delegation": "ValidatedPlanningReActAgent" in source,
            "timeline_postprocessing": "_fill_plan_timeline" in source,
            "independent_validation": "validate_trip_plan" in source,
        }
        present = [name for name, included in responsibilities.items() if included]
        print(f"TripPlanningService 编排职责探针: {present}")

        # 少于 4 个职责点时，入口很可能已退化为空壳转发层；这是临时架构护栏。
        self.assertGreaterEqual(len(present), 4, responsibilities)
        self.assertTrue(responsibilities["react_delegation"])
        self.assertTrue(responsibilities["independent_validation"])


if __name__ == "__main__":
    unittest.main()
