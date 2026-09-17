"""Chroma 用户偏好向量检索：跨会话语义召回 + 时间加权。

与 POI 向量库共用同一个 Chroma 持久化目录，但使用独立 collection。
每条偏好以 ``sha1(user_id|conversation_id)`` 为主键 upsert：同一会话的
偏好更新覆盖旧值，不同会话各自保留，从而支持按当前输入语义召回该用户
跨会话的历史偏好，并按"语义相关度 × 时间衰减"加权排序。
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
from .poi_vector_store import normalize_city_key

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
        print(f"用户偏好向量库已加载: {persist_path} / {settings.preference_collection_name}")

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


_store: PreferenceVectorStore | None = None


def get_preference_vector_store() -> PreferenceVectorStore | None:
    """懒加载 Chroma；未安装依赖或打开失败时返回 None，调用方按无偏好召回处理。"""
    global _store
    if _store is not None:
        return _store
    try:
        _store = PreferenceVectorStore()
    except Exception as error:
        print(f"⚠️ 用户偏好向量库不可用，跳过偏好召回: {type(error).__name__}: {error}")
        return None
    return _store
