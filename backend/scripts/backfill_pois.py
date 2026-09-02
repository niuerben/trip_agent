"""使用高德 POI 搜索结果预热 Chroma 向量库。

用法（在 backend 目录执行）：
    python scripts/backfill_pois.py --city 深圳 --keywords 景点 公园 美食 酒店

天气和路线不在此脚本的职责范围内，也不会写入 Chroma。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.amap_photo_service import get_amap_photo_service


def main() -> None:
    parser = argparse.ArgumentParser(description="将高德 POI 预热到 Chroma")
    parser.add_argument("--city", required=True, help="高德支持的城市名或 adcode")
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=["景点"],
        help="要搜索的 POI 关键词，可传多个",
    )
    parser.add_argument("--offset", type=int, default=20, help="每个关键词最多写入的 POI 数量")
    args = parser.parse_args()

    service = get_amap_photo_service()
    total = 0
    for keyword in args.keywords:
        pois = service.search_pois(keyword, city=args.city, offset=max(1, args.offset))
        total += len(pois)
        print(f"已缓存：城市={args.city}，关键词={keyword}，POI={len(pois)}")
    print(f"Chroma POI 预热完成：城市={args.city}，关键词={len(args.keywords)}，返回 POI={total}")


if __name__ == "__main__":
    main()
