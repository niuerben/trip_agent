"""基于 FunctionCallAgent 的旅行规划系统。"""

import json
from typing import Optional
from hello_agents import FunctionCallAgent
from hello_agents.tools import MCPTool
from ..services.llm_service import get_llm
from ..models.schemas import TripRequest, TripPlan, DayPlan, Attraction, Meal, WeatherInfo, Location, Hotel, Preference
from ..config import get_settings
from ..services.amap_photo_service import AmapPhotoService, get_amap_photo_service
from ..services.trip_plan_validator import validate_trip_plan

PLANNER_SYSTEM_PROMPT = """你是行旅天下的旅行规划 Agent，负责独立完成完整旅行计划。

你可以通过高德 MCP 工具获取 POI、天气、酒店、路线和图片信息。请自主判断需要调用哪些工具，
先获取事实数据，再生成计划。工具返回的数据优先级高于模型记忆，禁止编造高德没有返回的景点、酒店、
天气或图片信息。

规划要求：
1. 使用用户提供的城市、日期、交通、住宿和偏好。
2. 每天安排合理数量的景点，并考虑景点之间的距离和交通方式。
3. 每天安排早餐、午餐和晚餐。
4. 生成酒店、天气、预算和实用建议。
5. 当输入包含当前计划和修改要求时，只修改用户明确要求的内容，未涉及的日期和内容保持不变。
6. 工具失败时保留已确认的数据，不得用虚构内容替代工具结果。
7. 最终只返回符合 TripPlan JSON Schema 的 JSON，不要返回 Markdown 或解释文字。

最终 JSON 必须包含 city、start_date、end_date、days、weather_info、overall_suggestions；
每个 day 必须包含 date、day_index、description、transportation、accommodation、attractions 和 meals。
"""


class TripPlannerAgent:
    """使用单个 FunctionCallAgent 完成旅行规划。"""

    def __init__(self):
        """初始化单 Agent 旅行规划系统。"""
        print("🔄 开始初始化单 Agent 旅行规划系统...")

        try:
            settings = get_settings()
            self.llm = get_llm()

            print("  - 创建高德 MCP 工具...")
            self.amap_tool = MCPTool(
                name="amap",
                description="高德地图服务",
                server_command=["uvx", "amap-mcp-server"],
                env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
                auto_expand=True
            )
            self.amap_tool.expandable = True
            print("  - 创建单旅行规划 Agent...")
            self.agent = FunctionCallAgent(
                name="旅行规划 Agent",
                llm=self.llm,
                system_prompt=PLANNER_SYSTEM_PROMPT,
                max_tool_iterations=8,
            )
            self.agent.add_tool(self.amap_tool)

            print("✅ 单 Agent 旅行规划系统初始化成功")
            print(f"   MCP 工具数量: {len(self.agent.list_tools())}")

        except Exception as e:
            print(f"❌ 旅行规划 Agent 初始化失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
    
    def plan_trip(self, request: TripRequest, preference: Optional[Preference] = None) -> TripPlan:
        """使用一个支持原生工具调用的 Agent 完成旅行规划。"""
        preference = preference or Preference()
        try:
            print(f"\n{'=' * 60}")
            print("开始单 Agent 旅行规划...")
            print(f"目的地: {request.city}")
            print(f"日期: {request.start_date} 至 {request.end_date}")
            print(f"天数: {request.travel_days}天")
            print(f"偏好: {', '.join(request.preferences) if request.preferences else '无'}")
            if preference.prompt:
                print(f"偏好提示词: {preference.prompt[:100]}")
            print(f"{'=' * 60}\n")

            planner_query = self._build_planner_query(request, preference)
            planner_response = self.agent.run(
                planner_query,
                max_tool_iterations=8,
                tool_choice="auto",
            )
            print(f"规划 Agent 返回: {planner_response[:300]}...\n")

            trip_plan = self._parse_response(planner_response, request, preference)
            validate_trip_plan(trip_plan, request)
            return self._enrich_attraction_images(trip_plan)
        except Exception as error:
            print(f"旅行规划 Agent 失败: {type(error).__name__}: {error}")
            import traceback
            traceback.print_exc()
            if request.current_plan:
                try:
                    print("定向重规划失败，保留原旅行计划")
                    return TripPlan.model_validate(request.current_plan)
                except Exception as preserve_error:
                    print(f"原旅行计划无法恢复: {preserve_error}")
            return self._create_fallback_plan(
                request,
                "模型或高德服务响应超时/不可用",
                preference,
            )

    @staticmethod
    def _enrich_attraction_images(plan: TripPlan) -> TripPlan:
        """用高德 POI 校正景点坐标并补齐图片。

        一个城市只请求一次 POI 列表，再按景点名称匹配，避免为每个景点
        单独请求高德接口导致规划链路被网络 IO 拖慢。
        """
        settings = get_settings()
        if not settings.amap_api_key:
            return plan

        photo_service = get_amap_photo_service()
        attractions = [
            attraction
            for day in plan.days
            for attraction in day.attractions
        ]
        if not attractions:
            return plan

        try:
            pois = photo_service.search_pois(
                "景点",
                city=plan.city,
                offset=min(20, max(10, len(attractions) * 3)),
            )
        except Exception as error:
            print(f"⚠️ 高德图片补齐跳过: {type(error).__name__}: {error}")
            return plan

        def normalize(value: str) -> str:
            return "".join(str(value or "").split()).lower()

        normalized_pois = [
            (normalize(poi.get("name", "")), poi)
            for poi in pois
            if isinstance(poi, dict)
        ]
        for attraction in attractions:
            attraction_name = normalize(attraction.name)
            if not attraction_name:
                continue
            matched = False
            for poi_name, poi in normalized_pois:
                if not poi_name or not (
                    attraction_name in poi_name or poi_name in attraction_name
                ):
                    continue
                location = TripPlannerAgent._parse_poi_location(poi)
                if location:
                    # 高德 POI 的 location 已经是高德地图使用的 GCJ-02 坐标，
                    # 优先覆盖模型生成的近似坐标，避免地图标记偏移。
                    attraction.location = location
                photos = AmapPhotoService._extract_photos(poi)
                if photos and not TripPlannerAgent._is_amap_image_url(attraction.image_url):
                    attraction.image_url = photos[0]["url"]
                matched = True
                break

            # 学校、大学等 POI 经常不会出现在“景点”关键词列表中，
            # 对这些名称再发起一次精确查询，避免使用模型近似坐标。
            if not matched and any(
                marker in attraction.name
                for marker in ("大学", "学院", "学校", "校园")
            ):
                exact_cities = [plan.city]
                if plan.city.endswith("坪山"):
                    exact_cities.append("深圳")
                for exact_city in exact_cities:
                    try:
                        exact_pois = photo_service.search_pois(
                            attraction.name,
                            city=exact_city,
                            offset=10,
                        )
                    except Exception as error:
                        print(
                            f"⚠️ 高德精确 POI 坐标补齐跳过({attraction.name}): "
                            f"{type(error).__name__}: {error}"
                        )
                        continue
                    exact_match = next(
                        (
                            poi
                            for poi in exact_pois
                            if (
                                attraction_name in normalize(poi.get("name", ""))
                                or normalize(poi.get("name", "")) in attraction_name
                            )
                        ),
                        None,
                    )
                    if not exact_match:
                        continue
                    location = TripPlannerAgent._parse_poi_location(exact_match)
                    if location:
                        attraction.location = location
                    photos = AmapPhotoService._extract_photos(exact_match)
                    if photos and not TripPlannerAgent._is_amap_image_url(attraction.image_url):
                        attraction.image_url = photos[0]["url"]
                    break

        # 酒店和餐馆也可能只有名称没有坐标，按类别补一次高德 POI 坐标。
        route_targets = {
            "酒店": [day.hotel for day in plan.days if day.hotel],
            "餐厅": [
                meal
                for day in plan.days
                for meal in day.meals
            ],
        }
        for keywords, targets in route_targets.items():
            if not targets:
                continue
            try:
                pois = photo_service.search_pois(
                    keywords,
                    city=plan.city,
                    offset=min(20, max(10, len(targets) * 3)),
                )
            except Exception as error:
                print(f"⚠️ 高德{keywords}坐标补齐跳过: {type(error).__name__}: {error}")
                continue
            normalized_pois = [
                (normalize(poi.get("name", "")), poi)
                for poi in pois
                if isinstance(poi, dict)
            ]
            for target in targets:
                target_name = normalize(getattr(target, "name", ""))
                for poi_name, poi in normalized_pois:
                    if target_name and poi_name and (
                        target_name in poi_name or poi_name in target_name
                    ):
                        location = TripPlannerAgent._parse_poi_location(poi)
                        if location:
                            target.location = location
                        break
        return plan

    @staticmethod
    def _parse_poi_location(poi: dict) -> Optional[Location]:
        """解析高德 POI 的 ``经度,纬度`` 字符串。"""
        raw_location = str(poi.get("location") or "")
        try:
            longitude, latitude = (float(value) for value in raw_location.split(",", 1))
        except (TypeError, ValueError):
            return None
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            return None
        return Location(longitude=longitude, latitude=latitude)

    @staticmethod
    def _is_amap_image_url(url: Optional[str]) -> bool:
        """只接受高德图片地址，避免模型示例 URL 被直接展示。"""
        return bool(url) and "autonavi.com" in url.lower()
    
    def _build_planner_query(
        self,
        request: TripRequest,
        preference: Optional[Preference] = None,
    ) -> str:
        """构建单 Agent 查询，将规划和重规划上下文一次性传入。"""
        query = f"""请根据以下信息生成{request.city}的{request.travel_days}天旅行计划:

**基本信息:**
- 城市: {request.city}
- 日期: {request.start_date} 至 {request.end_date}
- 天数: {request.travel_days}天
- 交通方式: {request.transportation}
- 住宿: {request.accommodation}
- 偏好: {', '.join(request.preferences) if request.preferences else '无'}
"""
        if request.current_plan and request.change_request:
            query += f"""
**当前旅行计划(JSON):**
{json.dumps(request.current_plan, ensure_ascii=False)}

**定向修改要求:**
{request.change_request}

**定向修改规则:**
1. 只修改用户明确要求的日期、景点、餐饮、酒店、交通或预算。
2. 未被要求修改的日期和内容必须保留。
3. 返回完整的旅行计划 JSON，不能只返回修改片段。
"""
        if request.free_text_input:
            query += f"\n**额外要求:** {request.free_text_input}"
        if preference and preference.prompt:
            query += f"\n**用户偏好:** {preference.prompt}"

        return query

    def _parse_response(self, response: str, request: TripRequest, preference: Optional[Preference] = None) -> TripPlan:
        """
        解析Agent响应
        
        Args:
            response: Agent响应文本
            request: 原始请求
            
        Returns:
            旅行计划
        """
        try:
            # 尝试从响应中提取JSON
            # 查找JSON代码块
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            elif "```" in response:
                json_start = response.find("```") + 3
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            elif "{" in response and "}" in response:
                # 直接查找JSON对象
                json_start = response.find("{")
                json_end = response.rfind("}") + 1
                json_str = response[json_start:json_end]
            else:
                raise ValueError("响应中未找到JSON数据")
            
            # 解析JSON
            data = json.loads(json_str)
            
            # 转换为TripPlan对象
            trip_plan = TripPlan(**data)
            
            return trip_plan
            
        except Exception as e:
            print(f"⚠️  解析响应失败: {str(e)}")
            print(f"   将使用备用方案生成计划")
            if request.current_plan:
                try:
                    return TripPlan.model_validate(request.current_plan)
                except Exception:
                    pass
            return self._create_fallback_plan(request, "模型返回内容无法解析", preference)

    @staticmethod
    def _create_fallback_plan(
        request: TripRequest,
        fallback_reason: str = "未配置模型密钥",
        preference: Optional[Preference] = None,
    ) -> TripPlan:
        """创建备用计划(当Agent失败时)"""
        from datetime import datetime, timedelta

        poi_candidates = []
        weather_info = []
        try:
            from ..services.amap_photo_service import get_amap_photo_service

            keywords = request.preferences[0] if request.preferences else "景点"
            poi_candidates = get_amap_photo_service().search_pois(
                keywords,
                city=request.city,
                offset=max(6, request.travel_days * 2),
            )
        except Exception as error:
            print(f"高德 POI 兜底搜索失败: {error}")

        try:
            # 即使 LLM/MCP 初始化超时，天气仍通过高德 REST API 独立获取。
            from ..services.amap_service import get_amap_service

            weather_info = get_amap_service().get_weather(request.city)
        except Exception as error:
            print(f"高德天气兜底查询失败: {error}")
        
        # 解析日期
        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")
        
        # 创建每日行程
        days = []
        for i in range(request.travel_days):
            current_date = start_date + timedelta(days=i)

            attractions = []
            for j in range(2):
                poi_index = i * 2 + j
                poi = poi_candidates[poi_index] if poi_index < len(poi_candidates) else None
                if poi:
                    location_parts = str(poi.get("location", "")).split(",")
                    try:
                        location = Location(
                            longitude=float(location_parts[0]),
                            latitude=float(location_parts[1]),
                        )
                    except (IndexError, ValueError):
                        location = TripPlannerAgent._fallback_city_location(
                            request.city,
                            i,
                            j,
                        )
                    photos = AmapPhotoService._extract_photos(poi)
                    attractions.append(
                        Attraction(
                            name=poi.get("name") or f"{request.city}景点{j + 1}",
                            address=poi.get("address") or f"{request.city}市",
                            location=location,
                            visit_duration=120,
                            description=poi.get("type") or f"{request.city}的推荐地点",
                            category="景点",
                            image_url=photos[0]["url"] if photos else None,
                        )
                    )
                else:
                    attractions.append(
                        Attraction(
                            name=f"{request.city}景点{j + 1}",
                            address=f"{request.city}市",
                            location=TripPlannerAgent._fallback_city_location(
                                request.city,
                                i,
                                j,
                            ),
                            visit_duration=120,
                            description=f"这是{request.city}的著名景点",
                            category="景点",
                        )
                    )

            day_plan = DayPlan(
                date=current_date.strftime("%Y-%m-%d"),
                day_index=i,
                description=f"第{i+1}天行程",
                transportation=request.transportation,
                accommodation=request.accommodation,
                attractions=attractions,
                meals=[
                    Meal(type="breakfast", name=f"第{i+1}天早餐", description="当地特色早餐"),
                    Meal(type="lunch", name=f"第{i+1}天午餐", description="午餐推荐"),
                    Meal(type="dinner", name=f"第{i+1}天晚餐", description="晚餐推荐")
                ]
            )
            days.append(day_plan)
        
        overall_suggestions = (
            f"{fallback_reason}，已生成{request.city}{request.travel_days}日基础行程。"
            "服务恢复后可获得更精确的高德景点、天气和图片推荐。"
        )
        if preference and preference.prompt:
            overall_suggestions += f" 已记录你的偏好: {preference.prompt}"

        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=weather_info,
            overall_suggestions=overall_suggestions,
        )

    @staticmethod
    def _fallback_city_location(city: str, day_index: int, item_index: int) -> Location:
        """在高德暂不可用时使用城市级中心点，避免把深圳标到北京。"""
        city_centers = {
            "深圳": (114.0579, 22.5431),
            "深圳坪山": (114.3389, 22.7080),
            "化州": (110.6396, 21.6635),
            "陆丰": (115.6523, 22.9465),
            "北京": (116.4074, 39.9042),
        }
        longitude, latitude = next(
            (
                center
                for name, center in sorted(
                    city_centers.items(),
                    key=lambda item: len(item[0]),
                    reverse=True,
                )
                if name in city
            ),
            (113.2644, 23.1291),
        )
        offset = day_index * 0.002 + item_index * 0.001
        return Location(longitude=longitude + offset, latitude=latitude + offset)


# 全局单 Agent 实例
_trip_planner_agent = None


def get_trip_planner_agent() -> TripPlannerAgent:
    """获取单 Agent 旅行规划系统实例。"""
    global _trip_planner_agent

    if _trip_planner_agent is None:
        _trip_planner_agent = TripPlannerAgent()

    return _trip_planner_agent

