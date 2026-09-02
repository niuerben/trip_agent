"""Chroma POI 向量存储测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
import gc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    import chromadb  # noqa: F401
except ImportError:  # pragma: no cover - 允许未安装可选依赖的环境跳过
    chromadb = None

from backend.app.config import get_settings
from backend.app.services.poi_vector_store import PoiVectorStore, classify_poi_group


@unittest.skipIf(chromadb is None, "未安装 chromadb")
class PoiVectorStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = get_settings()
        self.old_path = self.settings.chroma_persist_directory
        self.old_collection = self.settings.chroma_collection_name
        self.temp_dir = tempfile.TemporaryDirectory(prefix="poi-vector-test-")
        self.settings.chroma_persist_directory = str(Path(self.temp_dir.name))
        self.settings.chroma_collection_name = "test_pois"
        self.store = PoiVectorStore()

    def tearDown(self) -> None:
        # Chroma 的 PersistentClient 会在进程级缓存 SQLite 连接。
        # 清理共享客户端后再删除临时目录，避免 Windows 文件锁导致测试退出报错。
        try:
            from chromadb.api.client import SharedSystemClient

            SharedSystemClient.clear_system_cache()
        except Exception:
            pass
        del self.store
        gc.collect()
        self.settings.chroma_persist_directory = self.old_path
        self.settings.chroma_collection_name = self.old_collection
        self.temp_dir.cleanup()

    def test_upsert_and_city_isolation(self) -> None:
        self.store.upsert_pois(
            [
                {
                    "id": "sz-1",
                    "name": "坪山中心公园",
                    "address": "深圳市坪山区坪山大道",
                    "type": "风景名胜;公园",
                    "location": "114.346,22.694",
                    "adcode": "440310",
                }
            ],
            "深圳",
        )
        self.store.upsert_pois(
            [
                {
                    "id": "ns-1",
                    "name": "南山公园",
                    "address": "深圳市南山区",
                    "type": "风景名胜;公园",
                    "location": "113.946,22.548",
                    "adcode": "440305",
                }
            ],
            "深圳",
        )
        self.store.upsert_pois(
            [
                {
                    "id": "bj-1",
                    "name": "故宫",
                    "address": "北京市东城区景山前街",
                    "type": "风景名胜;世界遗产",
                    "location": "116.397,39.918",
                    "adcode": "110101",
                }
            ],
            "北京",
        )
        self.store.upsert_pois(
            [
                {
                    "id": "xm-1",
                    "name": "鼓浪屿",
                    "address": "厦门市思明区",
                    "type": "风景名胜",
                    "location": "118.070,24.448",
                    "adcode": "350203",
                }
            ],
            "厦门",
        )

        results = self.store.search(
            "深圳 坪山 自然风光", city="深圳", adcode="440310", limit=10
        )

        self.assertEqual({item["city"] for item in results}, {"深圳"})
        self.assertEqual({item["poi_id"] for item in results}, {"sz-1"})
        self.assertTrue(all("longitude" in item and "latitude" in item for item in results))
        self.assertEqual(self.store.search("自然风光", city="不存在的城市"), [])

    def test_upsert_is_idempotent(self) -> None:
        poi = {
            "id": "sz-1",
            "name": "深圳技术大学",
            "address": "兰田路3002号",
            "type": "科教文化服务;学校",
            "location": "114.399831,22.700708",
            "adcode": "440310",
        }
        self.store.upsert_pois([poi], "深圳")
        self.store.upsert_pois([poi], "深圳")

        self.assertEqual(self.store.collection.count(), 1)
        result = self.store.search("深圳技术大学", city="深圳", limit=1)
        self.assertEqual(result[0]["poi_id"], "sz-1")
        self.assertEqual(result[0]["longitude"], 114.399831)
        self.assertEqual(result[0]["latitude"], 22.700708)

    def test_search_separates_major_poi_groups(self) -> None:
        self.store.upsert_pois([
            {
                "id": "meal-1", "name": "坪山客家餐厅", "address": "坪山路1号",
                "type": "餐饮服务;中餐厅", "location": "114.340,22.700", "adcode": "440310",
            },
            {
                "id": "hotel-1", "name": "坪山经济型酒店", "address": "坪山路2号",
                "type": "住宿服务;宾馆酒店", "location": "114.341,22.700", "adcode": "440310",
            },
            {
                "id": "park-1", "name": "坪山中心公园", "address": "坪山路3号",
                "type": "风景名胜;公园", "location": "114.342,22.700", "adcode": "440310",
            },
        ], "深圳")

        meals = self.store.search("深圳坪山 客家菜", "深圳", limit=10, poi_group="meal")
        hotels = self.store.search("深圳坪山 住宿", "深圳", limit=10, poi_group="hotel")
        attractions = self.store.search("深圳坪山 自然风光", "深圳", limit=10, poi_group="attraction")

        self.assertEqual({item["poi_id"] for item in meals}, {"meal-1"})
        self.assertEqual({item["poi_id"] for item in hotels}, {"hotel-1"})
        self.assertEqual({item["poi_id"] for item in attractions}, {"park-1"})
        self.assertEqual(classify_poi_group({"type": "餐饮服务;中餐厅"}), "meal")
        self.assertIsNone(classify_poi_group({"name": "深圳技术大学公交站", "type": "交通设施服务;公交车站"}))


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证 POI 写入、分类检索和城市隔离。")
