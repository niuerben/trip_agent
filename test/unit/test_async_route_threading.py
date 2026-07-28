"""异步 API 的阻塞边界测试。

高德和图片服务内部使用 requests/MCP 同步客户端；路由必须把这些调用移到
线程池，避免阻塞 FastAPI event loop。测试只替换服务对象，不访问真实网络。
"""

from __future__ import annotations

import sys
import unittest
import ast
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.api.routes import map as map_routes
from backend.app.api.routes import poi as poi_routes
from backend.app.models.schemas import RouteRequest


class _FakeAmapService:
    def search_poi(self, *args, **kwargs):
        return []

    def get_weather(self, *args, **kwargs):
        return []

    def plan_route(self, *args, **kwargs):
        return {
            "distance": 100.0,
            "duration": 60,
            "route_type": kwargs.get("route_type", "walking"),
            "description": "测试路线",
        }

    def get_poi_detail(self, *args, **kwargs):
        return {"id": args[0]}


class _FakePhotoService:
    def get_photo_url(self, *args, **kwargs):
        return "https://example.test/photo.jpg"


class AsyncRouteThreadingTest(unittest.IsolatedAsyncioTestCase):
    async def _assert_calls_run_in_thread(self, endpoint, *args, **kwargs):
        calls = []

        async def fake_to_thread(function, *function_args, **function_kwargs):
            calls.append((function, function_args, function_kwargs))
            return function(*function_args, **function_kwargs)

        with patch.object(map_routes.asyncio, "to_thread", side_effect=fake_to_thread), patch.object(
            poi_routes.asyncio, "to_thread", side_effect=fake_to_thread
        ):
            result = await endpoint(*args, **kwargs)

        self.assertTrue(calls, f"{endpoint.__name__} 未通过 asyncio.to_thread 调用同步服务")
        return result, calls

    async def test_map_routes_offload_sync_amap_clients(self) -> None:
        service = _FakeAmapService()
        with patch.object(map_routes, "get_amap_service", return_value=service):
            response, calls = await self._assert_calls_run_in_thread(
                map_routes.search_poi, keywords="公园", city="深圳"
            )
            self.assertTrue(response.success)
            self.assertEqual(calls[-1][0].__name__, "search_poi")

            response, calls = await self._assert_calls_run_in_thread(
                map_routes.get_weather, city="深圳"
            )
            self.assertTrue(response.success)
            self.assertEqual(calls[-1][0].__name__, "get_weather")

            request = RouteRequest(
                origin_address="起点",
                destination_address="终点",
                origin_city="深圳",
                destination_city="深圳",
            )
            response, calls = await self._assert_calls_run_in_thread(
                map_routes.plan_route, request
            )
            self.assertTrue(response.success)
            self.assertEqual(calls[-1][0].__name__, "plan_route")

    async def test_poi_and_photo_routes_offload_sync_clients(self) -> None:
        service = _FakeAmapService()
        photo_service = _FakePhotoService()
        with patch.object(poi_routes, "get_amap_service", return_value=service), patch.object(
            poi_routes, "get_amap_photo_service", return_value=photo_service
        ):
            response, calls = await self._assert_calls_run_in_thread(
                poi_routes.get_poi_detail, "POI-1"
            )
            self.assertTrue(response.success)
            self.assertEqual(calls[-1][0].__name__, "get_poi_detail")

            response, calls = await self._assert_calls_run_in_thread(
                poi_routes.search_poi, keywords="大学", city="深圳"
            )
            self.assertTrue(response["success"])
            self.assertEqual(calls[-1][0].__name__, "search_poi")

            response, calls = await self._assert_calls_run_in_thread(
                poi_routes.get_attraction_photo, name="深圳技术大学", city="深圳"
            )
            self.assertTrue(response["success"])
            self.assertEqual(calls[-1][0].__name__, "get_photo_url")

    def test_history_image_route_offloads_sync_geocoding(self) -> None:
        """历史计划补齐接口也不能在 async 函数中直接做同步地理编码。"""
        source_path = ROOT / "backend" / "app" / "api" / "routes" / "trip.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == "enrich_trip_images"
        )
        offloaded = {
            ast.unparse(node)
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_thread"
        }
        self.assertTrue(any("get_city_center" in call for call in offloaded), offloaded)
        self.assertTrue(any("get_city_adcode" in call for call in offloaded), offloaded)


if __name__ == "__main__":
    unittest.main()
