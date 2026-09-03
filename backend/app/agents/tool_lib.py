"""Domain search agents used by the planning ReAct loop."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, Dict, List, Mapping, Optional
from hello_agents.tools.base import Tool, ToolParameter

from ..api.routes.map import get_weather
from ..api.routes.poi import search_poi

from ..services.amap_service import AmapService, get_amap_service

class SearchAttraction(Tool):
    """ 一个搜索景点工具。当你需要搜索景点时，使用这个工具。 """

    def __init__(self) -> None:
        super().__init__(
            name="SearchAttraction",
            description="一个搜索景点工具。当你需要搜索景点时，使用这个工具。输入格式为SearchAttraction[keywords,city]",
        )

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            keywords, city = parameters["input"].split(",")
            return str({"result": asyncio.run(search_poi(keywords, city))})
        except Exception as e:
            return f'搜索错误：{e}'

    def get_parameters(self) -> List[ToolParameter]:
        return super().get_parameters()

class SearchWeather(Tool):
    """ 一个搜索天气工具。当你需要搜索天气时，使用这个工具。 """

    def __init__(self) -> None:
        super().__init__(
            name="SearchWeather",
            description="一个搜索天气工具。当你需要搜索天气时，使用这个工具。输入格式为SearchWeather[city]",
        )
        
    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            city = parameters["input"]
            return str({"result": asyncio.run(get_weather(city))})
        except Exception as e:
            return f'搜索错误：{e}'

    def get_parameters(self) -> List[ToolParameter]:
        return super().get_parameters()

class SearchHotel(Tool):
    """ 一个搜索酒店工具。当你需要搜索酒店时，使用这个工具。 """

    def __init__(self) -> None:
        super().__init__(
            name="SearchHotel",
            description="一个搜索酒店工具。当你需要搜索酒店时，使用这个工具。输入格式为SearchAttraction[keywords,city]",
        )
        
    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            keywords, city = parameters["input"].split(",")
            return str({"result": asyncio.run(search_poi(keywords, city))})
        except Exception as e:
            return f'搜索错误：{e}'

    def get_parameters(self) -> List[ToolParameter]:
        return super().get_parameters()

class SearchRestaurant(Tool):
    """ 一个搜索餐馆工具。当你需要搜索餐馆时，使用这个工具。 """
    def __init__(self) -> None:
        super().__init__(
            name="SearchRestaurant",
            description="一个搜索餐馆工具。当你需要搜索餐馆时，使用这个工具。输入格式为SearchRestaurant[keywords,city]",
        )
        
    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            keywords, city = parameters["input"].split(",")
            return str({"result": asyncio.run(search_poi(keywords, city))})
        except Exception as e:
            return f'搜索错误：{e}'

    def get_parameters(self) -> List[ToolParameter]:
        return super().get_parameters()
