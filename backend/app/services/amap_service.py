"""高德地图MCP服务封装"""

from functools import lru_cache
from typing import List, Dict, Any, Optional

import requests
from ..config import get_settings
from ..models.schemas import Location, POIInfo, WeatherInfo
from .mcp_logging import LoggingMCPTool

# 全局MCP工具实例
_amap_mcp_tool = None


def get_amap_mcp_tool() -> LoggingMCPTool:
    """
    获取高德地图MCP工具实例(单例模式)
    
    Returns:
        MCPTool实例
    """
    global _amap_mcp_tool
    
    if _amap_mcp_tool is None:
        settings = get_settings()
        
        if not settings.amap_api_key:
            raise ValueError("高德地图API Key未配置,请在.env文件中设置AMAP_API_KEY")
        
        # 创建MCP工具
        _amap_mcp_tool = LoggingMCPTool(
            name="amap",
            description="高德地图服务,支持POI搜索、路线规划、天气查询等功能",
            server_command=["uvx", "amap-mcp-server"],
            env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
            auto_expand=True  # 自动展开为独立工具
        )
        
        print(f"✅ 高德地图MCP工具初始化成功")
        print(f"   工具数量: {len(_amap_mcp_tool._available_tools)}")
        
        # 打印可用工具列表
        if _amap_mcp_tool._available_tools:
            print("   可用工具:")
            for tool in _amap_mcp_tool._available_tools[:5]:  # 只打印前5个
                print(f"     - {tool.get('name', 'unknown')}")
            if len(_amap_mcp_tool._available_tools) > 5:
                print(f"     ... 还有 {len(_amap_mcp_tool._available_tools) - 5} 个工具")
    
    return _amap_mcp_tool


class AmapService:
    """高德地图服务封装类"""

    PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
    WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"
    DAILY_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
    DRIVING_DIRECTION_URL = "https://restapi.amap.com/v5/direction/driving"
    TRANSIT_DIRECTION_URL = "https://restapi.amap.com/v5/direction/transit/integrated"

    def __init__(self):
        """初始化服务。MCP 仅在路线和详情接口使用时按需启动。"""
        settings = get_settings()
        self.api_key = settings.amap_api_key
        self.timeout = (
            settings.amap_connect_timeout_seconds,
            settings.amap_read_timeout_seconds,
        )
        self.mcp_tool: Optional[LoggingMCPTool] = None

    def _get_mcp_tool(self) -> LoggingMCPTool:
        """按需初始化 MCP，避免简单查询依赖 uvx/MCP 进程。"""
        if self.mcp_tool is None:
            self.mcp_tool = get_amap_mcp_tool()
        return self.mcp_tool
    
    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> List[POIInfo]:
        """
        搜索POI
        
        Args:
            keywords: 搜索关键词
            city: 城市
            citylimit: 是否限制在城市范围内
            
        Returns:
            POI信息列表
        """
        try:
            if not self.api_key:
                raise ValueError("AMAP_API_KEY未配置")

            response = requests.get(
                self.PLACE_TEXT_URL,
                params={
                    "key": self.api_key,
                    "keywords": keywords,
                    "city": city,
                    "citylimit": str(citylimit).lower(),
                    "extensions": "all",
                    "offset": 20,
                    "page": 1,
                    "output": "json",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("status")) != "1":
                raise RuntimeError(
                    f"高德 POI 查询失败: {payload.get('info')} "
                    f"(infocode={payload.get('infocode')})"
                )

            pois: List[POIInfo] = []
            for item in payload.get("pois") or []:
                raw_location = str(item.get("location") or "")
                try:
                    longitude, latitude = (
                        float(value) for value in raw_location.split(",", 1)
                    )
                except (TypeError, ValueError):
                    continue
                pois.append(
                    POIInfo(
                        id=str(item.get("id") or ""),
                        name=str(item.get("name") or ""),
                        type=str(item.get("type") or ""),
                        address=str(item.get("address") or ""),
                        location=Location(
                            longitude=longitude,
                            latitude=latitude,
                        ),
                        tel=item.get("tel") or None,
                    )
                )
            return pois
        except Exception as e:
            print(f"❌ POI搜索失败: {str(e)}")
            raise
    
    def get_weather(self, city: str) -> List[WeatherInfo]:
        """
        查询天气
        
        Args:
            city: 城市名称
            
        Returns:
            天气信息列表
        """
        try:
            if not self.api_key:
                raise ValueError("AMAP_API_KEY未配置")

            response = requests.get(
                self.WEATHER_URL,
                params={
                    "key": self.api_key,
                    "city": city,
                    "extensions": "all",
                    "output": "json",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("status")) != "1":
                raise RuntimeError(
                    f"高德天气查询失败: {payload.get('info')} "
                    f"(infocode={payload.get('infocode')})"
                )

            weather: List[WeatherInfo] = []
            for item in payload.get("forecasts", [{}])[0].get("casts", []):
                weather.append(
                    WeatherInfo(
                        date=str(item.get("date") or ""),
                        day_weather=str(item.get("dayweather") or ""),
                        night_weather=str(item.get("nightweather") or ""),
                        day_temp=item.get("daytemp") or 0,
                        night_temp=item.get("nighttemp") or 0,
                        wind_direction=str(item.get("daywind") or ""),
                        wind_power=str(item.get("daypower") or ""),
                    )
                )
            return weather
        except Exception as e:
            print(f"❌ 天气查询失败: {str(e)}")
            raise

    def get_weather_for_date(
        self,
        city: str,
        target_date: str,
        location: Optional[Location] = None,
    ) -> WeatherInfo:
        """仅查询一个缺失旅行日的逐日预报。

        高德天气接口不能传日期且只返回有限窗口，因此仅在高德结果缺少某个
        旅行日时，使用 Open-Meteo 的 start_date=end_date 精确补查该日期。
        """
        center = location or self.get_city_center(city)
        if center is None:
            raise ValueError(f"无法解析 {city} 的天气查询坐标")

        response = requests.get(
            self.DAILY_FORECAST_URL,
            params={
                "latitude": center.latitude,
                "longitude": center.longitude,
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "wind_direction_10m_dominant,wind_speed_10m_max"
                ),
                "timezone": "Asia/Shanghai",
                "start_date": target_date,
                "end_date": target_date,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        daily = response.json().get("daily") or {}
        dates = daily.get("time") or []
        if target_date not in dates:
            raise RuntimeError(f"逐日天气未返回目标日期 {target_date}")
        index = dates.index(target_date)

        weather_code = self._daily_value(daily, "weather_code", index, 0)
        weather_text = self._weather_code_text(int(weather_code))
        wind_degrees = float(self._daily_value(daily, "wind_direction_10m_dominant", index, 0))
        wind_speed = round(float(self._daily_value(daily, "wind_speed_10m_max", index, 0)))
        return WeatherInfo(
            date=target_date,
            day_weather=weather_text,
            night_weather=weather_text,
            day_temp=round(float(self._daily_value(daily, "temperature_2m_max", index, 0))),
            night_temp=round(float(self._daily_value(daily, "temperature_2m_min", index, 0))),
            wind_direction=self._wind_direction(wind_degrees),
            wind_power=f"{wind_speed} km/h",
            source="Open-Meteo",
        )

    @staticmethod
    def _daily_value(daily: dict, key: str, index: int, default: Any) -> Any:
        values = daily.get(key) or []
        return values[index] if index < len(values) else default

    @staticmethod
    def _weather_code_text(code: int) -> str:
        if code == 0:
            return "晴"
        if code in {1, 2}:
            return "多云"
        if code == 3:
            return "阴"
        if code in {45, 48}:
            return "雾"
        if 51 <= code <= 57:
            return "毛毛雨"
        if 61 <= code <= 67:
            return "雨"
        if 71 <= code <= 77:
            return "雪"
        if 80 <= code <= 82:
            return "阵雨"
        if 85 <= code <= 86:
            return "阵雪"
        if code in {95, 96, 99}:
            return "雷雨"
        return "天气变化"

    @staticmethod
    def _wind_direction(degrees: float) -> str:
        directions = ("北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风")
        return directions[round((degrees % 360) / 45) % 8]
    
    def get_city_center(self, city: str) -> Optional[Location]:
        """通过高德 REST 地理编码获取城市中心点(GCJ-02)。

        用作景点坐标越界判定的基准：任何距该中心超过阈值的坐标都视为跨城/跨省错误。
        走 REST 通道(不依赖 MCP/uvx)，结果按城市名做进程内缓存，避免每次规划重复请求。
        """
        normalized = (city or "").strip()
        if not normalized:
            return None
        center, _ = _get_city_geocode_cached(normalized, self.api_key, self.timeout)
        return center

    def get_city_adcode(self, city: str) -> Optional[str]:
        """返回高德行政区 adcode，用于区县级 POI 硬过滤。"""
        normalized = (city or "").strip()
        if not normalized:
            return None
        _, adcode = _get_city_geocode_cached(normalized, self.api_key, self.timeout)
        return adcode

    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking"
    ) -> Dict[str, Any]:
        """
        规划路线
        
        Args:
            origin_address: 起点地址
            destination_address: 终点地址
            origin_city: 起点城市
            destination_city: 终点城市
            route_type: 路线类型 (walking/driving/transit)
            
        Returns:
            路线信息
        """
        try:
            # 根据路线类型选择工具
            tool_map = {
                "walking": "maps_direction_walking_by_address",
                "driving": "maps_direction_driving_by_address",
                "transit": "maps_direction_transit_integrated_by_address"
            }
            
            tool_name = tool_map.get(route_type, "maps_direction_walking_by_address")
            
            # 构建参数
            arguments = {
                "origin_address": origin_address,
                "destination_address": destination_address
            }
            
            # 公共交通需要城市参数
            if route_type == "transit":
                if origin_city:
                    arguments["origin_city"] = origin_city
                if destination_city:
                    arguments["destination_city"] = destination_city
            else:
                # 其他路线类型也可以提供城市参数提高准确性
                if origin_city:
                    arguments["origin_city"] = origin_city
                if destination_city:
                    arguments["destination_city"] = destination_city
            
            # 调用MCP工具
            result = self._get_mcp_tool().run({
                "action": "call_tool",
                "tool_name": tool_name,
                "arguments": arguments
            })
            
            print(f"路线规划结果: {result[:200]}...")
            
            # TODO: 解析实际的路线数据
            return {}
            
        except Exception as e:
            print(f"❌ 路线规划失败: {str(e)}")
            return {}

    def get_route_geometry(
        self,
        origin: Location,
        destination: Location,
        city: str,
        route_type: str,
    ) -> Dict[str, Any]:
        """返回可直接绘制的高德道路/公共交通折线，不依赖浏览器 JS 插件。

        ``driving`` 提供道路几何；``transit`` 同时返回步行、公交与地铁的真实
        分段几何，前端可用不同颜色叠加展示，而不是以两点直线代替路线。
        """
        if not self.api_key:
            raise ValueError("AMAP_API_KEY未配置")
        origin_text = f"{origin.longitude},{origin.latitude}"
        destination_text = f"{destination.longitude},{destination.latitude}"
        if route_type == "transit":
            # v5 公共交通接口要求 city1/city2 为 adcode；中文城市名会返回
            # INVALID_PARAMS。地理编码结果已做进程缓存，不会重复命中网络。
            transit_city = self.get_city_adcode(city) or city
            url = self.TRANSIT_DIRECTION_URL
            params = {
                "key": self.api_key,
                "origin": origin_text,
                "destination": destination_text,
                "city1": transit_city,
                "city2": transit_city,
                "strategy": 0,
                "show_fields": "polyline",
                "output": "json",
            }
        else:
            url = self.DRIVING_DIRECTION_URL
            params = {
                "key": self.api_key,
                "origin": origin_text,
                "destination": destination_text,
                "strategy": 32,
                "show_fields": "cost,navi,polyline",
                "output": "json",
            }
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("status")) != "1":
            raise RuntimeError(
                f"高德{route_type}路线查询失败: {payload.get('info')} "
                f"(infocode={payload.get('infocode')})"
            )
        segments = (
            self._extract_transit_geometry(payload)
            if route_type == "transit"
            else self._extract_driving_geometry(payload)
        )
        return {"route_type": route_type, "segments": segments}

    @staticmethod
    def _parse_polyline(value: object) -> list[list[float]]:
        points: list[list[float]] = []
        for point in str(value or "").split(";"):
            try:
                longitude, latitude = (float(item) for item in point.split(",", 1))
            except (TypeError, ValueError):
                continue
            if -180 <= longitude <= 180 and -90 <= latitude <= 90:
                points.append([longitude, latitude])
        return points

    @classmethod
    def _extract_driving_geometry(cls, payload: dict) -> list[dict]:
        paths = (payload.get("route") or {}).get("paths") or []
        steps = paths[0].get("steps") if paths and isinstance(paths[0], dict) else []
        segments = []
        for step in steps or []:
            points = cls._parse_polyline(step.get("polyline") if isinstance(step, dict) else "")
            if len(points) >= 2:
                segments.append({"kind": "road", "points": points})
        return segments

    @classmethod
    def _extract_transit_geometry(cls, payload: dict) -> list[dict]:
        transits = (payload.get("route") or {}).get("transits") or []
        segments = transits[0].get("segments") if transits and isinstance(transits[0], dict) else []
        result: list[dict] = []
        for segment in segments or []:
            if not isinstance(segment, dict):
                continue
            walking = segment.get("walking") or {}
            for step in walking.get("steps") or []:
                points = cls._parse_polyline(step.get("polyline") if isinstance(step, dict) else "")
                if len(points) >= 2:
                    result.append({"kind": "walk", "points": points})
            bus = segment.get("bus") or {}
            for line in bus.get("buslines") or []:
                if not isinstance(line, dict):
                    continue
                points = cls._parse_polyline(line.get("polyline"))
                if len(points) < 2:
                    continue
                text = " ".join(str(line.get(key) or "") for key in ("name", "type"))
                kind = "subway" if any(word in text for word in ("地铁", "轨道", "城际")) else "bus"
                result.append({"kind": kind, "points": points})
        return result
    
    def geocode(self, address: str, city: Optional[str] = None) -> Optional[Location]:
        """
        地理编码(地址转坐标)

        Args:
            address: 地址
            city: 城市

        Returns:
            经纬度坐标
        """
        try:
            arguments = {"address": address}
            if city:
                arguments["city"] = city

            result = self._get_mcp_tool().run({
                "action": "call_tool",
                "tool_name": "maps_geo",
                "arguments": arguments
            })

            print(f"地理编码结果: {result[:200]}...")

            # TODO: 解析实际的坐标数据
            return None

        except Exception as e:
            print(f"❌ 地理编码失败: {str(e)}")
            return None

    def get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        """
        获取POI详情

        Args:
            poi_id: POI ID

        Returns:
            POI详情信息
        """
        try:
            result = self._get_mcp_tool().run({
                "action": "call_tool",
                "tool_name": "maps_search_detail",
                "arguments": {
                    "id": poi_id
                }
            })

            print(f"POI详情结果: {result[:200]}...")

            # 解析结果并提取图片
            import json
            import re

            # 尝试从结果中提取JSON
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data

            return {"raw": result}

        except Exception as e:
            print(f"❌ 获取POI详情失败: {str(e)}")
            return {}


@lru_cache(maxsize=256)
def _get_city_geocode_cached(
    city: str,
    api_key: str,
    timeout: tuple,
) -> tuple[Optional[Location], Optional[str]]:
    """缓存高德行政区中心和 adcode，避免同一次规划重复请求地理编码。"""
    if not api_key:
        return None, None
    try:
        response = requests.get(
            AmapService.GEOCODE_URL,
            params={
                "key": api_key,
                "address": city,
                "output": "json",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        print(f"⚠️ 高德城市中心解析跳过({city}): {type(error).__name__}: {error}")
        return None, None

    if str(payload.get("status")) != "1":
        print(
            f"⚠️ 高德城市中心解析返回非成功状态({city}): "
            f"{payload.get('info')} (infocode={payload.get('infocode')})"
        )
        return None, None

    geocodes = payload.get("geocodes") or []
    for item in geocodes:
        raw_location = str(item.get("location") or "") if isinstance(item, dict) else ""
        try:
            longitude, latitude = (float(value) for value in raw_location.split(",", 1))
        except (TypeError, ValueError):
            continue
        if -180 <= longitude <= 180 and -90 <= latitude <= 90:
            adcode = str(item.get("adcode") or item.get("citycode") or "").strip() or None
            return Location(longitude=longitude, latitude=latitude), adcode
    return None, None


# 创建全局服务实例
_amap_service = None


def get_amap_service() -> AmapService:
    """获取高德地图服务实例(单例模式)"""
    global _amap_service
    
    if _amap_service is None:
        _amap_service = AmapService()
    
    return _amap_service
