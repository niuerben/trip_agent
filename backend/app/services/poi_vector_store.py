"""Chroma 持久化 POI 向量检索。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..config import get_settings


POI_GROUPS = ("attraction", "hotel", "meal")


def normalize_city_key(city: str) -> str:
    """统一高德“广州市”和产品“广州”的 Chroma 分区键。"""
    value = (city or "").strip()
    return value[:-1] if len(value) > 2 and value.endswith("市") else value


def classify_poi_group(poi: dict[str, Any]) -> str | None:
    """把高德 POI 归入规划需要的三类，大类之外保留原始 type 给 Agent 判断小类。"""
    accessory_text = " ".join(
        str(poi.get(key) or "")
        for key in ("name", "type")
    )
    if any(marker in accessory_text for marker in (
        "公交站", "地铁站", "停车场", "停车位", "收费站", "出入口",
    )):
        return None
    typecode = str(poi.get("typecode") or "")
    text = " ".join(
        str(poi.get(key) or "")
        for key in ("name", "type", "typecode")
    ).lower()
    if any(marker in text for marker in (
        "住宿服务", "宾馆", "酒店", "旅馆", "民宿", "客栈", "公寓式酒店",
    )) or typecode.startswith("10"):
        return "hotel"
    if any(marker in text for marker in (
        "餐饮服务", "餐厅", "餐馆", "饭店", "快餐", "咖啡", "茶馆", "茶艺",
        "酒吧", "甜品", "小吃", "美食",
    )) or typecode.startswith("05"):
        return "meal"
    if any(marker in text for marker in (
        "风景名胜", "公园", "景区", "游乐园", "博物馆", "美术馆", "展览馆",
        "纪念馆", "文化宫", "动物园", "植物园", "科教文化服务", "学校", "大学",
        "学院", "体育休闲服务",
    )) or typecode.startswith(("11", "14", "15", "16", "18")):
        return "attraction"
    return None


class PoiVectorStore:
    """保存高德 POI 文本和坐标，并按城市元数据过滤检索。"""

    def __init__(self) -> None:
        import chromadb

        settings = get_settings()
        persist_path = Path(settings.chroma_persist_directory)
        if not persist_path.is_absolute():
            persist_path = Path(__file__).resolve().parents[2] / persist_path
        persist_path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_path))
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        # 使用 ASCII 前缀，兼容 Windows 默认 GBK 控制台。
        print(f"Chroma POI 向量库已加载: {persist_path}")

    @staticmethod
    def _id(poi: dict[str, Any], city: str) -> str:
        raw = "|".join(
            str(poi.get(key) or "")
            for key in ("id", "name", "address", "location")
        ) + f"|{city}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _document(poi: dict[str, Any], city: str) -> str:
        return " | ".join(
            value for value in (
                city,
                str(poi.get("name") or ""),
                str(poi.get("type") or ""),
                str(poi.get("address") or ""),
            ) if value
        )

    def upsert_pois(self, pois: list[dict[str, Any]], city: str) -> None:
        city = normalize_city_key(city)
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for poi in pois:
            location = str(poi.get("location") or "")
            if not poi.get("name") or "," not in location:
                continue
            try:
                longitude, latitude = (float(value) for value in location.split(",", 1))
            except ValueError:
                continue
            poi_group = classify_poi_group(poi)
            if poi_group is None:
                # 商务住宅、停车场等附属 POI 不作为旅行路线候选缓存。
                continue
            biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
            ids.append(self._id(poi, city))
            documents.append(self._document(poi, city))
            metadatas.append({
                "city": city,
                "adcode": str(poi.get("adcode") or ""),
                "poi_id": str(poi.get("id") or ""),
                "name": str(poi.get("name") or ""),
                "address": str(poi.get("address") or ""),
                "type": str(poi.get("type") or ""),
                "rating": str(biz_ext.get("rating") or ""),
                "cost": str(biz_ext.get("cost") or ""),
                "longitude": longitude,
                "latitude": latitude,
                "poi_group": poi_group,
            })
        if ids:
            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def search(
        self,
        query: str,
        city: str,
        limit: int = 10,
        adcode: str | None = None,
        poi_group: str | None = None,
        distance_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        city = normalize_city_key(city)
        if poi_group is not None and poi_group not in POI_GROUPS:
            raise ValueError(f"poi_group 必须是 {', '.join(POI_GROUPS)} 之一")
        if self.collection.count() == 0:
            return []
        threshold = (
            get_settings().poi_vector_distance_threshold
            if distance_threshold is None
            else distance_threshold
        )
        where: dict[str, Any] = {"city": city}
        if adcode:
            where = {"$and": [{"city": city}, {"adcode": adcode}]}
        # 旧数据可能没有 poi_group 元数据，因此按大类检索时先多取候选，
        # 再在 Python 中兼容推断并过滤，避免升级后必须清空 Chroma。
        fetch_limit = limit
        if poi_group:
            fetch_limit = min(max(limit * 5, 50), self.collection.count())
        result = self.collection.query(
            query_texts=[query],
            n_results=fetch_limit,
            where=where,
            include=["metadatas", "documents", "distances"],
        )
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        rows = []
        for metadata, distance in zip(metadatas, distances):
            if threshold >= 0 and (
                distance is None or float(distance) > threshold
            ):
                continue
            row = {**metadata, "distance": distance}
            row["poi_group"] = row.get("poi_group") or classify_poi_group(row)
            if poi_group and row["poi_group"] != poi_group:
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
        return rows


_store: PoiVectorStore | None = None


def get_poi_vector_store() -> PoiVectorStore | None:
    """懒加载 Chroma；未安装依赖时保持现有 REST/MCP 链路可用。"""
    global _store
    if _store is not None:
        return _store
    try:
        _store = PoiVectorStore()
    except Exception as error:
        print(f"⚠️ Chroma POI 向量库不可用，跳过向量检索: {type(error).__name__}: {error}")
        return None
    return _store
