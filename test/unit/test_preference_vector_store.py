"""用户偏好向量库测试：写入覆盖、用户隔离与时间加权召回。"""

from __future__ import annotations

import gc
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    import chromadb  # noqa: F401
except ImportError:  # pragma: no cover - 允许未安装可选依赖的环境跳过
    chromadb = None

from backend.app.config import get_settings
from backend.app.services.preference_vector_store import PreferenceVectorStore


@unittest.skipIf(chromadb is None, "未安装 chromadb")
class PreferenceVectorStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = get_settings()
        self.old_path = self.settings.chroma_persist_directory
        self.old_collection = self.settings.preference_collection_name
        self.temp_dir = tempfile.TemporaryDirectory(prefix="preference-vector-test-")
        self.settings.chroma_persist_directory = str(Path(self.temp_dir.name))
        self.settings.preference_collection_name = "test_preferences"
        self.store = PreferenceVectorStore()

    def tearDown(self) -> None:
        # Chroma 的 PersistentClient 会在进程级缓存 SQLite 连接，
        # 清理共享客户端后再删临时目录，避免 Windows 文件锁。
        try:
            from chromadb.api.client import SharedSystemClient

            SharedSystemClient.clear_system_cache()
        except Exception:
            pass
        del self.store
        gc.collect()
        self.settings.chroma_persist_directory = self.old_path
        self.settings.preference_collection_name = self.old_collection
        self.temp_dir.cleanup()

    def test_upsert_overwrites_same_conversation(self) -> None:
        now = time.time()
        self.assertTrue(self.store.upsert_preference(
            "喜欢自然风光，节奏悠闲", "user-1", "conv-1", city="深圳", updated_at=now
        ))
        # 同一会话偏好更新：覆盖而非新增。
        self.assertTrue(self.store.upsert_preference(
            "喜欢大学校园和博物馆", "user-1", "conv-1", city="深圳", updated_at=now + 60
        ))
        self.assertEqual(self.store.collection.count(), 1)

        rows = self.store.search_preferences("博物馆 校园", "user-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prompt"], "喜欢大学校园和博物馆")
        self.assertEqual(rows[0]["conversation_id"], "conv-1")

        # 空偏好或缺关键 ID 不写入。
        self.assertFalse(self.store.upsert_preference("", "user-1", "conv-1"))
        self.assertFalse(self.store.upsert_preference("偏好", "user-1", ""))

    def test_user_isolation(self) -> None:
        self.store.upsert_preference("想去北京看故宫", "user-1", "conv-1")
        self.store.upsert_preference("想去成都吃火锅", "user-2", "conv-2")

        rows_1 = self.store.search_preferences("故宫", "user-1")
        rows_2 = self.store.search_preferences("故宫", "user-2")

        # 各自只能召回自己的偏好，不能跨用户泄漏。
        self.assertEqual([row["conversation_id"] for row in rows_1], ["conv-1"])
        self.assertEqual([row["conversation_id"] for row in rows_2], ["conv-2"])

    def test_time_weighting_prefers_recent_preference(self) -> None:
        now = time.time()
        # 两份完全相同的文档 → 语义距离相同，排序完全由时间加权决定。
        self.store.upsert_preference(
            "喜欢自然风光和当地美食", "user-1", "conv-old", city="杭州",
            updated_at=now - 360 * 86400,
        )
        self.store.upsert_preference(
            "喜欢自然风光和当地美食", "user-1", "conv-new", city="杭州",
            updated_at=now,
        )

        rows = self.store.search_preferences("自然风光 美食", "user-1", limit=5, now=now)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["conversation_id"], "conv-new")
        self.assertGreater(rows[0]["score"], rows[1]["score"])

    def test_irrelevant_preference_filtered_by_distance(self) -> None:
        now = time.time()
        self.store.upsert_preference("喜欢自然风光徒步", "user-1", "conv-1", updated_at=now)
        self.store.upsert_preference("预算五星级酒店服务", "user-1", "conv-2", updated_at=now)

        rows = self.store.search_preferences(
            "自然风光 徒步路线", "user-1", limit=5,
            distance_threshold=0.5, now=now,
        )

        self.assertTrue(rows)
        self.assertTrue(all("自然风光" in row["prompt"] for row in rows))


if __name__ == "__main__":
    from test._output import run_unittest

    run_unittest("验证偏好写入覆盖、用户隔离和时间加权召回。")
