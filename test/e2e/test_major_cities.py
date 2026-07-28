"""五大城市真实浏览器 E2E 矩阵。

运行前需启动前端（5173）和后端（8000）：
    python test/e2e/test_major_cities.py --headless

每一项都必须实际登录、提交规划并跳转结果页；HTTP 504 不视为通过。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from test.e2e.test_trip_planner import TripTestCase, run_trip_planner_test


MAJOR_CITY_CASES: tuple[TripTestCase, ...] = tuple(
    TripTestCase(
        city=city,
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 29),
        preferences=("美食", "休闲"),
        transportation="公共交通",
        accommodation="经济型酒店",
        free_text_input="三人行，吃好吃的，玩好玩的，每餐预算人均不超过 40 元",
    )
    for city in ("北京", "上海", "广州", "深圳", "杭州")
)


def main() -> None:
    parser = argparse.ArgumentParser(description="运行北京、上海、广州、深圳、杭州 E2E 矩阵")
    parser.add_argument("--base-url", default="http://localhost:5173")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--cities",
        nargs="+",
        choices=[case.city for case in MAJOR_CITY_CASES],
        help="仅运行指定城市；省略时运行完整五城矩阵",
    )
    args = parser.parse_args()

    completed: list[tuple[str, str]] = []
    cases = (
        tuple(case for case in MAJOR_CITY_CASES if case.city in args.cities)
        if args.cities
        else MAJOR_CITY_CASES
    )
    for case in cases:
        print(f"\n{'=' * 72}\n【五城 E2E】城市={case.city}\n{'=' * 72}")
        result_url = run_trip_planner_test(
            case=case,
            base_url=args.base_url,
            headed=not args.headless,
        )
        completed.append((case.city, result_url))

    print("\n五城 E2E 全部通过：")
    for city, result_url in completed:
        print(f"- {city}: {result_url}")


if __name__ == "__main__":
    main()
