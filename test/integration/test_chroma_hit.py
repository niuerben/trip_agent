"""Chroma POI 命中测试。

在 test 目录运行：
    python integration/test_chroma_hit.py
    python integration/test_chroma_hit.py --city 深圳 --query 深圳坪山大学 --poi-group attraction
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "backend" / ".env", override=False)
except ImportError:
    pass

from backend.app.config import get_settings
from backend.app.services.poi_vector_store import POI_GROUPS, get_poi_vector_store


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查看 Chroma POI 命中结果")
    parser.add_argument("--city", help="城市过滤，例如：深圳")
    parser.add_argument("--query", help="查询词，例如：深圳坪山大学")
    parser.add_argument(
        "--poi-group",
        choices=POI_GROUPS,
        default=None,
        help="大类过滤：attraction、hotel、meal",
    )
    parser.add_argument("--adcode", default=None, help="行政区划代码，例如：440310")
    parser.add_argument(
        "--backend-url",
        default="http://localhost:8000",
        help="使用后端已预热的 Chroma 查询地址",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="直接在当前测试进程打开 Chroma，不通过后端",
    )
    parser.add_argument("--top-k", type=int, default=None, help="最多显示的命中数量")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="临时覆盖 Chroma 余弦距离阈值；距离越小越相似",
    )
    return parser.parse_args()


def main() -> int:
    total_started = time.perf_counter()
    args = _parse_args()
    settings = get_settings()

    # 测试默认值统一放在 main，脚本本身不使用终端交互输入。
    city = args.city or "深圳"
    query = args.query or "深圳坪山大学"
    poi_group = args.poi_group or "attraction"
    adcode = args.adcode
    top_k = args.top_k if args.top_k is not None else 10

    if args.threshold is not None:
        settings.poi_vector_distance_threshold = args.threshold
    threshold = settings.poi_vector_distance_threshold

    mode = "本地 Chroma" if args.direct else "后端 Chroma"
    print(f"【集成测试】test_chroma_hit | {mode}")
    print("说明：检查指定查询能否命中符合条件的 Chroma POI。")
    print(f"条件：城市={city}，查询={query}，大类={poi_group or '不限'}，TopK={top_k}")

    query_started = time.perf_counter()
    try:
        if args.direct:
            store_started = time.perf_counter()
            store = get_poi_vector_store()
            store_duration_ms = round((time.perf_counter() - store_started) * 1000, 3)
            if store is None:
                print("失败：Chroma 不可用")
                return 2
            results = store.search(
                query=query,
                city=city,
                limit=max(1, top_k),
                adcode=adcode,
                poi_group=poi_group,
                distance_threshold=threshold,
            )
        else:
            params = {
                "query": query,
                "city": city,
                "poi_group": poi_group,
                "adcode": adcode,
                "top_k": max(1, top_k),
                "threshold": threshold,
            }
            url = (
                args.backend_url.rstrip("/")
                + "/api/poi/vector-search?"
                + urlencode({key: value for key, value in params.items() if value is not None})
            )
            with urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            results = payload.get("data") or []
            meta = payload.get("meta") or {}
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"失败：后端 Chroma 查询失败（{error}）；可追加 --direct 检查本地库。")
        return 1
    except Exception as error:
        print(f"失败：{type(error).__name__}: {error}")
        return 1
    query_duration_ms = round((time.perf_counter() - query_started) * 1000, 3)
    total_duration_ms = round((time.perf_counter() - total_started) * 1000, 3)

    print(f"结果：命中 {len(results)} 条 | 查询 {query_duration_ms:.0f} ms | 总计 {total_duration_ms:.0f} ms")
    if not results:
        print("结论：未命中，上层将转高德 POI 搜索。")
        return 0

    for index, item in enumerate(results, start=1):
        print(
            f"  {index}. {item.get('name') or '未命名'}"
            f" | {item.get('poi_group') or '未分类'}"
            f" | 距离 {item.get('distance')}"
            f" | {item.get('address') or '无地址'}"
        )

    print("结论：以上候选可作为 Chroma 命中结果。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
