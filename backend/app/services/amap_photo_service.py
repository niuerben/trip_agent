"""高德地图图片服务

通过高德 Web 服务 REST API 的关键词搜索(extensions=all)获取 POI 官方图片。
参考: https://developer.amap.com/api/webservice/guide/api-advanced/search
"""

from functools import lru_cache
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import get_settings


class AmapPhotoService:
    """基于高德关键词搜索的图片服务"""

    BASE_URL = "https://restapi.amap.com/v3/place/text"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.amap_api_key
        self.timeout = (
            settings.amap_connect_timeout_seconds,
            settings.amap_read_timeout_seconds,
        )
        self.session = requests.Session()
        retry = Retry(
            total=max(0, settings.amap_request_retries),
            connect=max(0, settings.amap_request_retries),
            read=max(0, settings.amap_request_retries),
            status=max(0, settings.amap_request_retries),
            backoff_factor=0.2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _fetch_pois(self, keywords: str, city: str = "", offset: int = 3) -> List[dict]:
        """调用高德关键词搜索, 返回 pois 列表 (可能为空)"""
        if not self.api_key:
            print("⚠️  高德 API Key 未配置, 无法获取图片")
            return []

        params = {
            "key": self.api_key,
            "keywords": keywords,
            "extensions": "all",   # 关键: 只有 all 才会返回 photos
            "offset": offset,       # 每页数量, 取前 N 个候选
            "page": 1,
            "output": "json",
        }
        if city:
            params["city"] = city
            params["citylimit"] = "true"

        try:
            resp = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(
                "⚠️ 高德关键词搜索跳过: "
                f"{type(e).__name__}: {e}"
            )
            return []

        # status "1" 表示成功
        if str(data.get("status")) != "1":
            print(f"⚠️  高德返回非成功状态: {data.get('info')} (infocode={data.get('infocode')})")
            return []

        return data.get("pois") or []

    @staticmethod
    def _extract_photos(poi: dict) -> List[dict]:
        """从单个 POI 中提取可用的图片, 已做 http→https 归一化"""
        raw_photos = poi.get("photos") or []
        cleaned: List[dict] = []
        for p in raw_photos:
            url = p.get("url") if isinstance(p, dict) else None
            if not url:
                continue
            if url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            title = p.get("title") if isinstance(p, dict) else ""
            cleaned.append({
                "url": url,
                "title": title if isinstance(title, str) else "",
            })
        return cleaned

    def get_photos(self, keywords: str, city: str = "") -> List[dict]:
        """获取 POI 的所有候选图片 (遍历前几条 POI, 直到拿到 photos)"""
        pois = self._fetch_pois(keywords, city=city, offset=3)
        for poi in pois:
            photos = self._extract_photos(poi)
            if photos:
                return photos
        return []

    def search_pois(self, keywords: str, city: str = "", offset: int = 10) -> List[dict]:
        """返回带图片扩展字段的高德 POI 原始结果。"""
        pois = self._fetch_pois(keywords, city=city, offset=offset)
        try:
            from .poi_vector_store import get_poi_vector_store

            store = get_poi_vector_store()
            if store:
                store.upsert_pois(pois, city)
        except Exception as error:
            print(f"⚠️ POI 写入 Chroma 跳过: {type(error).__name__}: {error}")
        return pois

    def get_photo_url(self, keywords: str, city: str = "") -> Optional[str]:
        """获取单张图片 URL(命中缓存, 找不到返回 None)"""
        return _get_photo_url_cached(keywords.strip(), (city or "").strip())


@lru_cache(maxsize=512)
def _get_photo_url_cached(keywords: str, city: str) -> Optional[str]:
    """按 (keywords, city) 做进程内缓存, 减少重复请求 (受高德 QPS 限制)"""
    service = get_amap_photo_service()
    photos = service.get_photos(keywords, city=city)
    if photos:
        return photos[0]["url"]
    return None


# 单例
_amap_photo_service: Optional[AmapPhotoService] = None


def get_amap_photo_service() -> AmapPhotoService:
    global _amap_photo_service
    if _amap_photo_service is None:
        _amap_photo_service = AmapPhotoService()
    return _amap_photo_service
