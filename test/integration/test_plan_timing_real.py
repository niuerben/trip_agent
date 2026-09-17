"""真实规划链路计划生成平均用时测试。

覆盖北京、上海、广州、深圳、杭州 5 城共 10 条用例（每城 2 条，统一 2 日行程），
直接调用真实 TripPlanningService.plan_trip 统计单次规划耗时与平均用时。

该测试会实际调用真实 LLM 与高德接口，产生费用并可能限流，必须显式运行：

    $env:RUN_REAL_SERVICE_TESTS = "1"
    python -m unittest test.integration.test_plan_timing_real -v

需要 backend/.env 中配置 LLM_API_KEY/LLM_BASE_URL 和 AMAP_API_KEY。
每次运行的耗时明细写入被 Git 忽略的 test-artifacts/plan_timing/。
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "backend" / ".env", override=False)
except ImportError:
    pass

from test._gates import require_real_service_tests, test_artifact_dir

from backend.app.config import get_settings
from backend.app.models.schemas import Preference, TripRequest
from backend.app.services.trip_planning_service import (
    TripPlanningService,
    get_trip_planning_service,
)


@dataclass(frozen=True)
class TimingCase:
    """一条计时用例：统一 2 日行程，只变化城市与偏好，保证耗时可比。"""

    city: str
    preferences: list[str]
    free_text: str


# 北上广深杭各 2 条；天数、交通、住宿保持一致，排除变量让用时差异来自城市与偏好。
TIMING_CASES: list[TimingCase] = [
    TimingCase("北京", ["城市文化", "美食"], "安排经典历史文化与烤鸭美食行程。"),
    TimingCase("北京", ["自然风光", "亲子"], "安排适合亲子出游的自然风光行程。"),
    TimingCase("上海", ["城市文化", "购物"], "安排外滩地标与南京路购物行程。"),
    TimingCase("上海", ["美食", "艺术"], "安排带艺术展览与小资美食的行程。"),
    TimingCase("广州", ["美食", "城市文化"], "安排早茶美食与珠江城市文化行程。"),
    TimingCase("广州", ["自然风光", "休闲"], "安排轻松休闲的自然风光行程。"),
    TimingCase("深圳", ["主题乐园", "科技"], "安排主题乐园与科技展馆行程。"),
    TimingCase("深圳", ["海滨", "亲子"], "安排深圳湾海滨与亲子活动行程。"),
    TimingCase("杭州", ["自然风光", "城市文化"], "安排西湖、灵隐寺自然人文行程。"),
    TimingCase("杭州", ["美食", "休闲"], "安排杭帮菜美食与龙井茶休闲行程。"),
]

# 固定未来日期，避免"从今天起"的动态日期让多次运行结果不可比。
START_DATE = "2026-10-12"
END_DATE = "2026-10-13"
TRAVEL_DAYS = 2
_BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _build_request(case: TimingCase) -> TripRequest:
    return TripRequest(
        city=case.city,
        start_date=START_DATE,
        end_date=END_DATE,
        travel_days=TRAVEL_DAYS,
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences=list(case.preferences),
        free_text_input=case.free_text,
    )


class PlanGenerationTimingTest(unittest.TestCase):
    """统计真实链路下 10 条用例的计划生成平均用时。"""

    @classmethod
    def setUpClass(cls) -> None:
        require_real_service_tests("真实规划用时基准测试")
        settings = get_settings()
        if not (settings.llm_api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")):
            raise unittest.SkipTest("未配置真实 LLM_API_KEY/OPENAI_API_KEY")
        if not (
            settings.amap_api_key
            or os.getenv("AMAP_API_KEY")
            or os.getenv("AMAP_MAPS_API_KEY")
        ):
            raise unittest.SkipTest("未配置真实 AMAP_API_KEY")

        # 初始化（含 Chroma/MCP 懒加载）单独计时，不计入单次规划耗时。
        init_started = time.perf_counter()
        cls.planner: TripPlanningService = get_trip_planning_service()
        cls.init_duration_s = time.perf_counter() - init_started
        cls.settings = settings

    def test_plan_generation_average_time(self) -> None:
        settings = self.settings
        print(
            f"\n规划用时基准 | planner_mode={settings.planner_mode}"
            f" | deterministic={settings.planner_preloaded_deterministic_plan}"
            f" | 服务初始化 {self.init_duration_s:.1f} s（不计入单次规划）"
        )

        results: list[dict] = []
        for index, case in enumerate(TIMING_CASES, start=1):
            with self.subTest(city=case.city, preferences=case.preferences):
                request = _build_request(case)
                preference = Preference(prompt=case.free_text)
                started = time.perf_counter()
                error_text: str | None = None
                plan_days = 0
                try:
                    plan = self.planner.plan_trip(request, preference)
                    plan_days = len(plan.days)
                    self.assertEqual(
                        plan_days,
                        TRAVEL_DAYS,
                        f"{case.city} 行程天数不符：期望 {TRAVEL_DAYS} 天，实际 {plan_days} 天",
                    )
                except Exception as error:  # noqa: BLE001 - 单用例失败不中断其余城市
                    error_text = f"{type(error).__name__}: {error}"
                    raise
                finally:
                    duration_s = time.perf_counter() - started
                    results.append({
                        "index": index,
                        "city": case.city,
                        "preferences": case.preferences,
                        "duration_s": round(duration_s, 2),
                        "plan_days": plan_days,
                        "error": error_text,
                    })
                    status = f"{duration_s:.1f} s" if error_text is None else f"失败（{duration_s:.1f} s）"
                    print(f"  {index}. [{case.city}] {status} | 偏好: {'/'.join(case.preferences)}")

        succeeded = [item for item in results if item["error"] is None]
        failed = [item for item in results if item["error"] is not None]
        total_duration = sum(item["duration_s"] for item in succeeded)
        avg_duration = total_duration / len(succeeded) if succeeded else 0.0

        print(f"结果：成功 {len(succeeded)}/10 | 平均用时 {avg_duration:.1f} s"
              f" | 总计 {total_duration:.1f} s"
              + (f" | 失败用例：{', '.join(item['city'] for item in failed)}" if failed else ""))
        if succeeded:
            slowest = max(succeeded, key=lambda item: item["duration_s"])
            fastest = min(succeeded, key=lambda item: item["duration_s"])
            print(f"结论：最快 {fastest['city']} {fastest['duration_s']} s，"
                  f"最慢 {slowest['city']} {slowest['duration_s']} s。")

        self._write_artifact(results, avg_duration)
        # 真实服务波动大：只要求至少一半用例成功，平均值本身作观察指标不作断言。
        self.assertGreaterEqual(
            len(succeeded),
            len(TIMING_CASES) // 2,
            f"超过一半用例失败：{failed}",
        )

    @staticmethod
    def _write_artifact(results: list[dict], avg_duration: float) -> None:
        artifact_dir = test_artifact_dir() / "plan_timing"
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(_BEIJING_TZ).strftime("%Y%m%d_%H%M%S")
            path = artifact_dir / f"timing_{stamp}.json"
            payload = {
                "timestamp": datetime.now(_BEIJING_TZ).isoformat(timespec="seconds"),
                "planner_mode": get_settings().planner_mode,
                "deterministic": get_settings().planner_preloaded_deterministic_plan,
                "average_duration_s": round(avg_duration, 2),
                "cases": results,
            }
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"耗时明细已写入 {path}")
        except Exception as error:
            print(f"耗时明细写入失败: {type(error).__name__}: {error}")


if __name__ == "__main__":
    unittest.main()
