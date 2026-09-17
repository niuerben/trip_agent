"""Chroma POI 向量检索平均命中率测试。

覆盖北京、上海、广州、深圳、杭州 5 城，共 10 条用例（每城 attraction/hotel/meal 混合），
直接查询本地 Chroma 缓存（默认）或运行中的后端，统计平均命中率与平均查询耗时。

在仓库根目录运行：
    python test/integration/test_chroma_hit_rate.py
    python test/integration/test_chroma_hit_rate.py --direct --min-rate 0.5
    python test/integration/test_chroma_hit_rate.py --backend-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "backend" / ".env", override=False)
except ImportError:
    pass

from backend.app.config import get_settings
from backend.app.services.poi_vector_store import POI_GROUPS, get_poi_vector_store


@dataclass(frozen=True)
class HitRateCase:
    """一条命中率用例：命中条件是阈值内返回结果，且结果城市与目标城市一致。"""

    city: str
    query: str
    poi_group: str


# 北上广深杭各 2 条，覆盖 attraction / hotel / meal 三大类。
HIT_RATE_CASES: list[HitRateCase] = [
    HitRateCase("北京", "天安门 故宫 历史文化景点", "attraction"),
    HitRateCase("北京", "北京烤鸭 老字号餐厅", "meal"),
    HitRateCase("上海", "外滩 陆家嘴 城市地标", "attraction"),
    HitRateCase("上海", "外滩附近 高星酒店 住宿", "hotel"),
    HitRateCase("广州", "广州塔 珠江新城 地标景点", "attraction"),
    HitRateCase("广州", "广州早茶 虾饺 点心", "meal"),
    HitRateCase("深圳", "世界之窗 主题公园", "attraction"),
    HitRateCase("深圳", "深圳湾 科技园 酒店", "hotel"),
    HitRateCase("杭州", "西湖 灵隐寺 自然风光", "attraction"),
    HitRateCase("杭州", "杭州本帮菜 西湖醋鱼 餐厅", "meal"),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统计 Chroma POI 向量检索平均命中率")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="直接在当前测试进程打开本地 Chroma（默认行为）",
    )
    parser.add_argument(
        "--backend-url",
        default=None,
        help="改为访问运行中后端的 /api/poi/vector-search 接口",
    )
    parser.add_argument("--top-k", type=int, default=None, help="每次检索返回的候选数上限")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="临时覆盖 Chroma 余弦距离阈值；距离越小越相似",
    )
    parser.add_argument(
        "--min-rate",
        type=float,
        default=0.5,
        help="命中率低于该值时退出码为 1（设为 0 可只观察不判定）",
    )
    return parser.parse_args()


def _search_via_backend(
    backend_url: str,
    case: HitRateCase,
    top_k: int,
    threshold: float,
) -> list[dict]:
    params = {
        "query": case.query,
        "city": case.city,
        "poi_group": case.poi_group,
        "top_k": top_k,
        "threshold": threshold,
    }
    url = (
        backend_url.rstrip("/")
        + "/api/poi/vector-search?"
        + urlencode({key: value for key, value in params.items() if value is not None})
    )
    with urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("data") or []


def _search_direct(
    store,
    case: HitRateCase,
    top_k: int,
    threshold: float,
) -> list[dict]:
    return store.search(
        query=case.query,
        city=case.city,
        limit=top_k,
        poi_group=case.poi_group,
        distance_threshold=threshold,
    )


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    if args.threshold is not None:
        settings.poi_vector_distance_threshold = args.threshold
    threshold = settings.poi_vector_distance_threshold
    top_k = args.top_k if args.top_k is not None else settings.poi_vector_top_k

    mode = f"后端 Chroma（{args.backend_url}）" if args.backend_url else "本地 Chroma"
    print(f"【集成测试】test_chroma_hit_rate | {mode}")
    print(
        "说明：统计北上广深杭 10 条用例的向量检索命中率，"
        "命中条件 = 阈值内返回结果且城市过滤正确。"
    )
    print(f"条件：用例数={len(HIT_RATE_CASES)}，大类=attraction/hotel/meal 混合，"
          f"TopK={top_k}，距离阈值={threshold}，最低命中率={args.min_rate}")

    store = None
    if not args.backend_url:
        store = get_poi_vector_store()
        if store is None:
            print("失败：Chroma 不可用（未安装依赖或本地库无法打开）")
            return 2
        if store.collection.count() == 0:
            print("失败：本地 Chroma 为空，请先跑一次真实规划预热缓存再测命中率")
            return 2

    hits = 0
    total_duration_ms = 0.0
    leaked_cities: list[str] = []

    for index, case in enumerate(HIT_RATE_CASES, start=1):
        started = time.perf_counter()
        try:
            if args.backend_url:
                results = _search_via_backend(args.backend_url, case, top_k, threshold)
            else:
                results = _search_direct(store, case, top_k, threshold)
        except (HTTPError, URLError, TimeoutError) as error:
            print(f"  {index}. [{case.city}/{case.poi_group}] 失败：后端查询异常（{error}）")
            continue
        except Exception as error:
            print(f"  {index}. [{case.city}/{case.poi_group}] 失败：{type(error).__name__}: {error}")
            continue
        duration_ms = (time.perf_counter() - started) * 1000
        total_duration_ms += duration_ms

        wrong_city = [
            item for item in results
            if item.get("city") and item.get("city") != case.city
        ]
        if wrong_city:
            leaked_cities.append(case.city)
        hit = bool(results) and not wrong_city
        if hit:
            hits += 1

        top = results[0] if results else None
        top_text = (
            f"{top.get('name') or '未命名'} | 距离 {top.get('distance')}"
            if top else "无候选"
        )
        status = "✅ 命中" if hit else "❌ 未命中"
        leak_text = " | ⚠️ 混入其他城市结果" if wrong_city else ""
        print(
            f"  {index}. [{case.city}/{case.poi_group}] {status}"
            f" | 候选 {len(results)} 条 | {duration_ms:.0f} ms{leak_text}"
        )
        print(f"     Top1: {top_text} | 查询: {case.query}")

    total = len(HIT_RATE_CASES)
    hit_rate = hits / total if total else 0.0
    avg_duration_ms = total_duration_ms / total if total else 0.0
    print(f"结果：平均命中率 {hits}/{total} = {hit_rate:.0%}"
          f" | 平均查询 {avg_duration_ms:.0f} ms"
          + (f" | 城市过滤泄漏：{', '.join(leaked_cities)}" if leaked_cities else ""))

    if hit_rate >= 1.0:
        print("结论：全部用例命中，向量缓存覆盖良好。")
    elif hit_rate >= args.min_rate:
        print(f"结论：命中率 {hit_rate:.0%} 达到最低要求 {args.min_rate:.0%}，"
              "未命中用例依赖高德实时搜索兜底。")
    else:
        print(f"结论：命中率 {hit_rate:.0%} 低于最低要求 {args.min_rate:.0%}，"
              "对应城市的缓存可能尚未预热。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
