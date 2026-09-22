"""Chroma 向量库：POI 持久化缓存（原 poi_vector_store.py）
+ 用户偏好跨会话语义召回（原 preference_vector_store.py）。

两者共用同一个 Chroma 持久化目录，但使用各自独立 collection。
"""

from __future__ import annotations

import hashlib
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..config import get_settings

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------

def normalize_city_key(city: str) -> str:
    """统一高德“广州市”和产品“广州”的 Chroma 分区键。"""
    value = (city or "").strip()
    return value[:-1] if len(value) > 2 and value.endswith("市") else value


# ---------------------------------------------------------------------------
# POI 向量缓存
# ---------------------------------------------------------------------------

POI_GROUPS = ("attraction", "hotel", "meal")
DINING_ROOT_TYPECODE = "050000"


def classify_poi_group(poi: dict[str, Any]) -> str | None:
    """按既有三大组归类，优先使用高德 typecode，缺失时保留关键词回退。"""
    accessory_text = " ".join(
        str(poi.get(key) or "")
        for key in ("name", "type")
    )
    if any(marker in accessory_text for marker in (
        "公交站", "地铁站", "停车场", "停车位", "收费站", "出入口",
    )):
        return None

    typecode = str(poi.get("typecode") or "").strip()
    if typecode.startswith("05"):
        return "meal"
    if typecode.startswith("10"):
        return "hotel"
    if typecode.startswith(("11", "14", "15", "16", "18")):
        return "attraction"

    text = " ".join(
        str(poi.get(key) or "")
        for key in ("name", "type", "typecode")
    ).lower()
    if any(marker in text for marker in (
        "住宿服务", "宾馆", "酒店", "旅馆", "民宿", "客栈", "公寓式酒店",
    )):
        return "hotel"
    if any(marker in text for marker in (
        "餐饮服务", "餐厅", "餐馆", "饭店", "快餐", "咖啡", "茶馆", "茶艺",
        "酒吧", "甜品", "小吃", "美食",
    )):
        return "meal"
    if any(marker in text for marker in (
        "风景名胜", "公园", "景区", "游乐园", "博物馆", "美术馆", "展览馆",
        "纪念馆", "文化宫", "动物园", "植物园", "科教文化服务", "学校", "大学",
        "学院", "体育休闲服务",
    )):
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
        logger.info(f"Chroma POI 向量库已加载: {persist_path}")

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


_poi_store: PoiVectorStore | None = None


def get_poi_vector_store() -> PoiVectorStore | None:
    """懒加载 Chroma；未安装依赖时保持现有 REST/MCP 链路可用。"""
    global _poi_store
    if _poi_store is not None:
        return _poi_store
    try:
        _poi_store = PoiVectorStore()
    except Exception as error:
        logger.warning(f"⚠️ Chroma POI 向量库不可用，跳过向量检索: {type(error).__name__}: {error}")
        return None
    return _poi_store


# ---------------------------------------------------------------------------
# 用户偏好向量检索（原 preference_vector_store.py）
#
# 每条偏好以 ``sha1(user_id|conversation_id)`` 为主键 upsert：同一会话的
# 偏好更新覆盖旧值，不同会话各自保留，从而支持按当前输入语义召回该用户
# 跨会话的历史偏好，并按"语义相关度 × 时间衰减"加权排序。
# ---------------------------------------------------------------------------

_BEIJING_TZ = ZoneInfo("Asia/Shanghai")


class PreferenceVectorStore:
    """保存用户偏好文本，并按 user_id 元数据过滤检索。"""

    def __init__(self) -> None:
        import chromadb

        settings = get_settings()
        persist_path = Path(settings.chroma_persist_directory)
        if not persist_path.is_absolute():
            persist_path = Path(__file__).resolve().parents[2] / persist_path
        persist_path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_path))
        self.collection = self.client.get_or_create_collection(
            name=settings.preference_collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"用户偏好向量库已加载: {persist_path} / {settings.preference_collection_name}")

    @staticmethod
    def _id(user_id: str, conversation_id: str) -> str:
        return hashlib.sha1(f"{user_id}|{conversation_id}".encode("utf-8")).hexdigest()

    def upsert_preference(
        self,
        prompt: str,
        user_id: str,
        conversation_id: str,
        city: str = "",
        updated_at: float | None = None,
    ) -> bool:
        """写入或覆盖某会话的偏好；prompt 为空时忽略。"""
        prompt = (prompt or "").strip()
        if not prompt or not user_id or not conversation_id:
            return False
        epoch = time.time() if updated_at is None else float(updated_at)
        updated_iso = datetime.fromtimestamp(epoch, _BEIJING_TZ).isoformat(timespec="seconds")
        self.collection.upsert(
            ids=[self._id(user_id, conversation_id)],
            documents=[prompt],
            metadatas=[{
                "user_id": str(user_id),
                "conversation_id": str(conversation_id),
                "city": normalize_city_key(city) if city else "",
                "updated_epoch": epoch,
                "updated_at": updated_iso,
            }],
        )
        return True

    def search_preferences(
        self,
        query: str,
        user_id: str,
        limit: int | None = None,
        distance_threshold: float | None = None,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        """按语义召回该用户跨会话的历史偏好，时间加权排序。

        score = (1 - distance) * 0.5 ** (age_days / half_life)。
        返回字段：prompt / conversation_id / city / updated_at / distance / score。
        """
        settings = get_settings()
        limit = limit or settings.preference_vector_top_k
        threshold = (
            settings.preference_vector_distance_threshold
            if distance_threshold is None
            else distance_threshold
        )
        query = (query or "").strip()
        if not query or self.collection.count() == 0:
            return []
        fetch_limit = min(self.collection.count(), max(limit * 5, 50))
        result = self.collection.query(
            query_texts=[query],
            n_results=fetch_limit,
            where={"user_id": user_id},
            include=["metadatas", "documents", "distances"],
        )
        metadatas = (result.get("metadatas") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        current = time.time() if now is None else float(now)
        half_life = max(0.1, settings.preference_recency_half_life_days)
        rows = []
        for metadata, document, distance in zip(metadatas, documents, distances):
            if threshold >= 0 and (distance is None or float(distance) > threshold):
                continue
            age_days = max(0.0, (current - float(metadata.get("updated_epoch") or current)) / 86400)
            relevance = 1.0 - float(distance) if distance is not None else 0.0
            rows.append({
                "prompt": str(document or ""),
                "conversation_id": str(metadata.get("conversation_id") or ""),
                "city": str(metadata.get("city") or ""),
                "updated_at": str(metadata.get("updated_at") or ""),
                "age_days": round(age_days, 2),
                "distance": distance,
                "score": round(relevance * math.pow(0.5, age_days / half_life), 6),
            })
        rows.sort(key=lambda row: row["score"], reverse=True)
        return rows[:limit]


_preference_store: PreferenceVectorStore | None = None


def get_preference_vector_store() -> PreferenceVectorStore | None:
    """懒加载 Chroma；未安装依赖或打开失败时返回 None，调用方按无偏好召回处理。"""
    global _preference_store
    if _preference_store is not None:
        return _preference_store
    try:
        _preference_store = PreferenceVectorStore()
    except Exception as error:
        logger.warning(f"⚠️ 用户偏好向量库不可用，跳过偏好召回: {type(error).__name__}: {error}")
        return None
    return _preference_store
