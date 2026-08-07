"""Domain search agents used by the planning ReAct loop."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping, Optional

from ..services.amap_service import AmapService, get_amap_service


ATTRACTION_AGENT_PROMPT = """你是景点搜索专家。
必须使用景点搜索工具获取真实数据，禁止编造景点名称、地址和坐标。
根据城市和用户偏好搜索适合的景点，只返回工具查询结果。
"""

WEATHER_AGENT_PROMPT = """你是天气查询专家。
必须使用天气查询工具获取真实天气数据，禁止凭常识猜测天气。
根据城市查询天气信息，只返回工具查询结果。
"""

HOTEL_AGENT_PROMPT = """你是酒店搜索专家。
必须使用酒店搜索工具获取真实酒店数据，禁止编造酒店名称、地址和价格。
根据城市和住宿偏好搜索酒店，只返回工具查询结果。
"""

RESTAURANT_AGENT_PROMPT = """你是餐厅搜索专家。
必须使用餐厅搜索工具获取真实餐厅数据，禁止编造餐厅名称、地址和评分。
根据城市、菜系和用户偏好搜索餐厅，只返回工具查询结果。
"""


class SearchAgent:
    """Common interface for domain search agents."""

    tool_name = "search"
    system_prompt = """你是旅行信息搜索专家。
必须通过已注册工具查询真实数据，禁止编造结果。
"""

    def __init__(self, service: Optional[AmapService] = None) -> None:
        self.service = service or get_amap_service()
        self.last_result: Any = None
        self.tools: Mapping[str, Callable[[Any], Any]] = {
            self.tool_name: self.search,
        }

    def search(self, arguments: Any) -> Any:
        raise NotImplementedError

    def tooluse(self, prompt: Any) -> Any:
        actions = self.normalise_actions(prompt)
        if not actions:
            self.last_result = {"passed": False, "error": "未提供有效搜索 Action"}
            return self.last_result
        result: Any = None
        for action in actions:
            name = action.get("name") if isinstance(action, dict) else None
            if name not in self.tools:
                result = {"passed": False, "error": f"{self.__class__.__name__} 不支持工具: {name}"}
                continue
            result = self.tools[name](action.get("arguments", {}))
        self.last_result = result
        return result

    @staticmethod
    def normalise_actions(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
        if not isinstance(value, str):
            return []
        text = value.strip()
        match = re.match(r"(?is)^(?:Action\s*:\s*)?([A-Za-z_]\w*)\s*\[(.*)\]$", text)
        if not match:
            return []
        try:
            arguments = json.loads(match.group(2))
        except json.JSONDecodeError:
            arguments = {}
        return [{"name": match.group(1), "arguments": arguments}]


class WeatherAgent(SearchAgent):
    tool_name = "search_weather"
    system_prompt = WEATHER_AGENT_PROMPT

    def search(self, arguments: Any) -> Any:
        city = str(arguments.get("city") if isinstance(arguments, dict) else arguments or "")
        return {"result": self.service.get_weather(city)}


class AttractionAgent(SearchAgent):
    tool_name = "search_attraction"
    system_prompt = ATTRACTION_AGENT_PROMPT

    def search(self, arguments: Any) -> Any:
        return self._search_poi(arguments, "景点")

    def _search_poi(self, arguments: Any, default_keyword: str) -> dict[str, Any]:
        payload = arguments if isinstance(arguments, dict) else {}
        city = str(payload.get("city") or "")
        keywords = str(payload.get("keywords") or default_keyword)
        return {"result": self.service.search_poi(keywords, city)}


class HotelAgent(AttractionAgent):
    tool_name = "search_hotel"
    system_prompt = HOTEL_AGENT_PROMPT

    def search(self, arguments: Any) -> Any:
        return self._search_poi(arguments, "酒店")


class RestaurantAgent(AttractionAgent):
    tool_name = "search_restaurant"
    system_prompt = RESTAURANT_AGENT_PROMPT

    def search(self, arguments: Any) -> Any:
        return self._search_poi(arguments, "餐厅")
