"""基于 FunctionCallAgent 的旅行规划系统。"""

import json
import math
import re
from itertools import combinations, permutations, product
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import date, timedelta
from typing import Optional
from ..services.llm_service import get_llm
from ..models.schemas import (
    Attraction,
    ChangeOperation,
    ChangeSet,
    DayPlan,
    Hotel,
    Location,
    Meal,
    Preference,
    TripPlan,
    TripRequest,
    WeatherInfo,
)
from ..config import get_settings
from ..services.amap_photo_service import AmapPhotoService, get_amap_photo_service
from ..services.trip_plan_validator import (
    TripPlanValidationError,
    is_within_city,
    validate_trip_plan,
)
from ..services.poi_vector_store import classify_poi_group
from .planning_react_agent import (
    PlanningSession,
    PlanningToolset,
    ValidatedPlanningReActAgent,
)

def _normalize_city_for_amap(city: str) -> str:
    """标准化城市名给高德 API，避免区县名导致 citylimit 失效搜出外地结果。

    高德 REST API 的 city 参数要求地级市名或 adcode，传区县名（如"深圳坪山"）
    会被当模糊查询，citylimit 约束失效，返回全国热门 POI（如北京西单）。
    这里做简单映射：区县 → 所属地级市，保证 citylimit 生效。
    """
    city = (city or "").strip()
    # 常见区县 → 地级市映射（按需扩充）
    mappings = {
        "深圳坪山": "深圳",
        "深圳龙岗": "深圳",
        "深圳宝安": "深圳",
        "深圳龙华": "深圳",
        "深圳光明": "深圳",
        "深圳大鹏": "深圳",
        "深圳盐田": "深圳",
        "陆丰": "汕尾",
        "化州": "茂名",
    }
    return mappings.get(city, city)


_DISTRICT_SCOPES = {
    "深圳坪山": ("深圳", "坪山"),
    "深圳坪山区": ("深圳", "坪山"),
    "深圳龙岗": ("深圳", "龙岗"),
    "深圳龙岗区": ("深圳", "龙岗"),
    "深圳宝安": ("深圳", "宝安"),
    "深圳宝安区": ("深圳", "宝安"),
    "深圳龙华": ("深圳", "龙华"),
    "深圳龙华区": ("深圳", "龙华"),
    "深圳光明": ("深圳", "光明"),
    "深圳光明区": ("深圳", "光明"),
    "深圳盐田": ("深圳", "盐田"),
    "深圳盐田区": ("深圳", "盐田"),
    "深圳大鹏": ("深圳", "大鹏新区"),
    "深圳大鹏新区": ("深圳", "大鹏新区"),
}

def _district_keyword(city: str) -> str:
    """返回区县级搜索词；地级市请求返回空字符串。"""
    return _DISTRICT_SCOPES.get((city or "").strip(), ("", ""))[1]


def _is_district_request(city: str) -> bool:
    return bool(_district_keyword(city))


def _is_district_adcode(adcode: Optional[str]) -> bool:
    """高德六位 adcode 末两位非 00 时表示区县级行政区。"""
    value = str(adcode or "").strip()
    return len(value) == 6 and value.isdigit() and not value.endswith("00")


class TripPlannerAgent:
    """准备规划上下文并委托给受 Validator 约束的 ReAct Agent。"""

    def __init__(self):
        """初始化薄规划入口；领域工具由每次 ReAct 会话按请求创建。"""
        print("🔄 开始初始化 ReAct 旅行规划系统...")

        try:
            self.llm = get_llm()
            self.agent_name = "旅行规划 ReAct Agent"
            self.tools_count = 2
            print("✅ ReAct 旅行规划系统初始化成功")
            print("   领域工具数量: 2")

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

            # 行政区中心和 adcode 只查询一次，后续 Chroma/坐标校验共用。
            settings = get_settings()
            city_center = None
            city_adcode = None
            amap_city = _normalize_city_for_amap(request.city)
            try:
                from ..services.amap_service import get_amap_service

                amap_service = get_amap_service()
                city_center = amap_service.get_city_center(request.city)
                city_adcode = amap_service.get_city_adcode(request.city)
                get_search_city = getattr(amap_service, "get_poi_search_city", None)
                if callable(get_search_city):
                    amap_city = get_search_city(request.city) or amap_city
            except Exception as error:
                print(f"⚠️ 目标行政区解析失败: {type(error).__name__}: {error}")

            district_scope = (
                _is_district_request(request.city)
                or _is_district_adcode(city_adcode)
            )
            radius_km = (
                settings.district_geo_radius_km
                if district_scope
                else settings.city_geo_radius_km
            )
            scope_adcode = city_adcode if district_scope else None
            # Chroma 首次 query 可能触发嵌入模型初始化，不能让它吞掉
            # 用户侧 60 秒预算。超出短预算时直接使用高德预取 POI，完成后
            # 的向量查询仍可自然结束并为后续请求热身。
            vector_pois = []
            if scope_adcode is None:
                # 市级缓存跨越整个行政区，语义相似不等于路线相近；并且首次
                # Chroma query 会初始化嵌入模型。五大城市完整规划直接围绕
                # 核心景点预取高德 POI，既快又能形成紧凑片区。
                print("市级完整规划跳过全城 Chroma 召回，使用核心景点附近高德 POI。")
            else:
                vector_executor = ThreadPoolExecutor(max_workers=1)
                vector_future = vector_executor.submit(
                    self._retrieve_cached_pois,
                    request,
                    preference,
                    adcode=scope_adcode,
                    amap_city=amap_city,
                )
                try:
                    vector_pois = vector_future.result(timeout=getattr(
                        settings, "planner_vector_retrieval_timeout_seconds", 3
                    ))
                except FuturesTimeoutError:
                    print("Chroma 召回超过 3 秒预算，直接预取高德 POI。")
                    vector_executor.shutdown(wait=False, cancel_futures=True)
                else:
                    vector_executor.shutdown(wait=True)
            change_set = request.change_set
            requires_full_replan = bool(
                change_set
                and any(operation.operation == "full_replan" for operation in change_set.operations)
            )
            if request.current_plan and change_set and not requires_full_replan:
                original_plan = TripPlan.model_validate(request.current_plan)
                try:
                    trip_plan, changes = self._execute_change_set(
                        original_plan.model_copy(deep=True),
                        change_set,
                        request,
                        vector_pois,
                        scope_adcode,
                    )
                    validate_trip_plan(
                        trip_plan,
                        request,
                        city_center=city_center,
                        radius_km=radius_km,
                        require_enriched_locations=True,
                    )
                    print(
                        "定向重规划完成: " + "；".join(changes)
                        + "；未重新检索酒店、餐厅、天气或路线。"
                    )
                    return trip_plan
                except TripPlanValidationError as validation_error:
                    # 旧计划含占位餐馆等遗留缺陷时，把已执行的局部修改作为
                    # Draft 交给 ReAct，根据 Validator Observation 定向补齐。
                    print(f"定向修改后的 Draft 需继续修复: {validation_error}")
                    request.current_plan = trip_plan.model_dump()
                except ValueError as change_set_error:
                    # Talk LLM 有时能正确识别重规划意图，却为餐饮等当前局部执行器
                    # 尚未表达的变更输出空操作。此时保留原计划，转由 ReAct 根据完整
                    # 上下文和 change_request 完成真实 POI 检索及校验，避免把“已更新”
                    # 变成 422 或仅修改一段文案。
                    print(
                        "ChangeSet 无法局部执行，转入 ReAct 定向重规划: "
                        f"{change_set_error}"
                    )
                    request.current_plan = original_plan.model_dump()

            planner_query = self._build_planner_query(request, preference, vector_pois)
            planning_session = PlanningSession(
                request=request,
                city_center=city_center,
                radius_km=radius_km,
                target_adcode=scope_adcode,
                amap_city=amap_city,
                cached_pois=vector_pois,
            )
            planning_tools = PlanningToolset(planning_session)
            preloaded = (
                settings.planner_preload_poi_evidence
                and planning_tools.prepare_required_evidence()
            )
            if preloaded:
                print("已预取餐饮、景点和酒店 POI 证据；优先用确定性近邻排程。")
            else:
                print("POI 预取不完整，回退到按需 ReAct 检索。")
            trip_plan = None
            if preloaded and settings.planner_preloaded_deterministic_plan:
                draft = self._build_evidence_plan(request, planning_session)
                if draft is not None:
                    validation = json.loads(planning_tools.validate_draft(
                        draft.model_dump_json()
                    ))
                    # 候选数量足够并不代表能排出满足相邻距离约束的路线。
                    # 先各 refresh 一次餐馆/景点，给高德和 Chroma 一个补充
                    # 局部片区候选的机会，再把扩充后的证据重新交给确定性排程。
                    if (
                        not validation.get("passed")
                        and any(
                            issue.get("code") == "ROUTE_LEG_TOO_LONG"
                            for issue in validation.get("issues", [])
                        )
                    ):
                        refreshed = False
                        for purpose, query, category in (
                            ("meal", f"{request.city} 平价餐馆", "餐饮服务"),
                            ("attraction", f"{request.city} 景点", "风景名胜"),
                        ):
                            result = json.loads(planning_tools.search_poi(json.dumps({
                                "purpose": purpose,
                                "query": query,
                                "category": category,
                                "refresh": True,
                            }, ensure_ascii=False)))
                            refreshed = refreshed or result.get("source") == "amap"
                        if refreshed:
                            retry_draft = self._build_evidence_plan(
                                request, planning_session
                            )
                            if retry_draft is not None:
                                retry_validation = json.loads(
                                    planning_tools.validate_draft(
                                        retry_draft.model_dump_json()
                                    )
                                )
                                if retry_validation.get("passed"):
                                    draft = retry_draft
                                    validation = retry_validation
                                    print("已扩充高德餐馆/景点证据，重新排程通过 Validator。")
                    if validation.get("passed"):
                        trip_plan = planning_session.validated_plan
                        print("POI 证据近邻排程已通过 Validator；跳过长 JSON 模型调用。")
                    else:
                        issues = validation.get("issues") or []
                        issue_text = "；".join(
                            str(issue.get("message") or issue.get("code") or issue)
                            for issue in issues
                        )
                        print(
                            "确定性排程未通过 Validator，回退到 ReAct。"
                            + (f" 原因: {issue_text}" if issue_text else "")
                        )
            if trip_plan is None:
                planner_response = ValidatedPlanningReActAgent(
                    llm=self.llm,
                    session=planning_session,
                ).run(planner_query)
                print(f"规划 Agent 返回: {planner_response[:300]}...\n")
                trip_plan = planning_session.validated_plan
                if trip_plan is None:
                    raise RuntimeError("ReAct 已结束，但没有通过 Validator 的旅行计划")
            # ReAct 已经完成内容选择；日期归属由规划入口根据请求统一落盘，
            # 保证每个 Chroma 餐馆都挂在明确的旅行日 day.meals 下。
            trip_plan = self._fill_plan_timeline(trip_plan, request)
            # 模型负责选择真实 POI；再由确定性近邻排序消除同一天内不必要的
            # 东西折返。地图和路线卡片会使用这一顺序绘制道路导航。
            trip_plan = self._order_day_attractions_by_proximity(trip_plan)
            weather_facts = trip_plan.weather_info
            if not weather_facts:
                try:
                    from ..services.amap_service import get_amap_service

                    weather_facts = get_amap_service().get_weather(
                        amap_city
                    )
                except Exception as weather_error:
                    print(f"高德短期天气查询失败，改为按缺失日期补查: {weather_error}")
            trip_plan.weather_info = self._complete_weather_for_travel_dates(
                weather_facts,
                request,
                city_center,
            )

            if request.current_plan and (request.change_set or request.change_request):
                previous_plan = TripPlan.model_validate(request.current_plan)
                if trip_plan.model_dump() == previous_plan.model_dump():
                    raise ValueError("规划 Agent 未实际修改旅行计划")

            # enrichment 先跑：校正坐标 + 用高德在城 POI 替换越界景点，
            # 再交给 validate 做最终闸门（修复失败才报错触发降级）。
            trip_plan = self._enrich_attraction_images(
                trip_plan,
                city_center=city_center,
                radius_km=radius_km,
                target_adcode=scope_adcode,
                amap_city=amap_city,
            )
            validate_trip_plan(
                trip_plan,
                request,
                city_center=city_center,
                radius_km=radius_km,
                require_enriched_locations=True,
            )
            return trip_plan
        except Exception as error:
            print(f"旅行规划 Agent 失败: {type(error).__name__}: {error}")
            import traceback
            traceback.print_exc()
            # 未通过 ReAct + Validator 的计划禁止用占位数据伪装成功。
            raise

    @staticmethod
    def _fill_plan_timeline(plan: TripPlan, request: TripRequest) -> TripPlan:
        """为 Agent 已选出的每日内容补齐请求日期和从 0 开始的 day_index。"""
        try:
            start = date.fromisoformat(request.start_date)
        except ValueError:
            return plan
        for index, day in enumerate(plan.days):
            day.date = (start + timedelta(days=index)).isoformat()
            day.day_index = index
        return plan

    @staticmethod
    def _meal_cost(candidate: dict, budget_limit: int | None) -> int:
        """从 POI 证据读取人均价；高德缺价时给出保守的到店预估。"""
        raw_cost = str(candidate.get("cost") or "").strip()
        match = re.search(r"\d+(?:\.\d+)?", raw_cost)
        cost = int(float(match.group())) if match else 30
        return min(cost, budget_limit) if budget_limit and cost > budget_limit else cost

    @staticmethod
    def _requested_meal_budget(request: TripRequest) -> int | None:
        """识别“人均不超过 40 元”一类约束，供候选优先级使用。"""
        text = " ".join((request.free_text_input or "", *request.preferences))
        matched = re.search(r"(?:人均|每餐|餐饮)?.{0,12}(?:不超过|不高于|最多|预算)\s*(\d+)\s*元", text)
        return int(matched.group(1)) if matched else None

    @classmethod
    def _build_evidence_plan(
        cls,
        request: TripRequest,
        session: PlanningSession,
    ) -> TripPlan | None:
        """在完整 POI 证据已准备好时，快速生成一个可审计的近邻计划。

        结构化的日期、坐标和餐饮类型不需要模型推理。直接由已检索的真实
        POI 组合，既消除长 JSON 的模型延迟，也让“餐饮不重复、相邻不跨区”
        成为算法约束而非提示词愿望。任何证据不够或无法排出合格路线时返回
        ``None``，保留原 ReAct 路径处理复杂请求。
        """
        meal_records = list(session.evidence_records.get("meal", {}).values())
        attraction_records = list(session.evidence_records.get("attraction", {}).values())
        hotel_records = list(session.evidence_records.get("hotel", {}).values())
        if not attraction_records:
            return None
        required_types = [
            item.strip()
            for item in get_settings().required_meal_types.split(",")
            if item.strip()
        ]
        required_meal_count = request.travel_days * len(required_types)
        budget_limit = cls._requested_meal_budget(request)

        def valid_record(record: dict) -> bool:
            return bool(record.get("poi_id") and cls._parse_poi_location(record))

        meals = [record for record in meal_records if valid_record(record)]
        if budget_limit:
            affordable = [
                record for record in meals
                if cls._meal_cost(record, None) <= budget_limit
            ]
            # 缺少价格的高德 POI 不应让全程无法生成；它们会以保守预算展示。
            if len(affordable) >= required_meal_count:
                meals = affordable
        if len(meals) < required_meal_count:
            return None

        # 先按地理投影排序，再切成每日固定数量。旧的“从剩余集合取最近邻”
        # 会在南山这类南北狭长区域把一个中部餐馆塞进西丽组，造成
        # 景点→午餐超过路段阈值的 Validator 失败。经纬度排序形成连续片区，
        # 再由下面的排列搜索决定当天的早餐/午餐/晚餐顺序。
        ordered_meals = sorted(
            meals,
            key=lambda item: (
                cls._parse_poi_location(item).latitude,
                cls._parse_poi_location(item).longitude,
            ),
        )
        meals_per_day = len(required_types)

        attractions = [record for record in attraction_records if valid_record(record)]
        hotels = [record for record in hotel_records if valid_record(record)]
        if not attractions or not hotels:
            return None
        # 同一行程默认住同一家酒店，避免每天搬运行李。市级酒店检索已围绕
        # 核心景点执行，这里再选择离餐饮片区质心最近的一家作为每日锚点。
        route_meals = ordered_meals[:required_meal_count]
        meal_locations = [cls._parse_poi_location(item) for item in route_meals]
        meal_center = Location(
            longitude=sum(item.longitude for item in meal_locations) / len(meal_locations),
            latitude=sum(item.latitude for item in meal_locations) / len(meal_locations),
        )
        selected_hotel = min(
            hotels,
            key=lambda item: cls._geo_distance_squared(
                meal_center, cls._parse_poi_location(item)
            ),
        )
        selected_hotel_location = cls._parse_poi_location(selected_hotel)
        start = date.fromisoformat(request.start_date)
        days: list[DayPlan] = []
        # 每天选择一个真实景点，保证景点证据在多日计划中不重复。

        def route_score(group: list[dict], selected: list[dict]):
            """返回“酒店出发并返回酒店”路线的最坏腿和总距离。"""
            attraction_locations = [cls._parse_poi_location(item) for item in selected]
            best = None
            for ordered in permutations(group):
                sequence = [selected_hotel_location, cls._parse_poi_location(ordered[0])]
                for index, attraction_location in enumerate(attraction_locations):
                    sequence.append(attraction_location)
                    if index + 1 < len(ordered):
                        sequence.append(cls._parse_poi_location(ordered[index + 1]))
                sequence.extend(
                    cls._parse_poi_location(item)
                    for item in ordered[len(attraction_locations) + 1:]
                )
                sequence.append(selected_hotel_location)
                legs = [
                    cls._geo_distance_squared(left, right)
                    for left, right in zip(sequence, sequence[1:])
                ]
                score = (max(legs), sum(legs), ordered)
                if best is None or score[:2] < best[:2]:
                    best = score
            return best

        def partitions(items: list[dict], groups_left: int):
            """枚举小规模餐馆分组；三天九餐最多约 280 种分法。"""
            if groups_left == 1:
                if items:
                    yield [items]
                return
            # 固定每层的第一个元素属于当前组，消除仅因组顺序不同的
            # 重复分支（9 餐/3 天从 1680 个排列降为约 280 个分组）。
            anchor = items[0]
            for tail in combinations(items[1:], meals_per_day - 1):
                picked = (anchor, *tail)
                picked_ids = {id(item) for item in picked}
                rest = [item for item in items if id(item) not in picked_ids]
                for tail in partitions(rest, groups_left - 1):
                    yield [list(picked), *tail]

        # 同时优化“餐馆分组”和“景点归属”。单独先分餐馆再按质心选景点，
        # 无法处理景点位于两个餐馆片区之间的情况，容易制造一条超长路线。
        best_assignment = None
        available_attractions = attractions
        for groups in partitions(
            ordered_meals[: request.travel_days * meals_per_day],
            request.travel_days,
        ):
            if len(available_attractions) >= request.travel_days:
                attraction_assignments = permutations(
                    available_attractions, request.travel_days
                )
            else:
                # 证据只有一个景点时允许跨日复用；Validator 只要求每天有
                # 景点，不把真实景点不足误判为模型格式错误。
                attraction_assignments = product(
                    available_attractions, repeat=request.travel_days
                )
            for assigned in attraction_assignments:
                scores = [
                    route_score(group, [attraction])
                    for group, attraction in zip(groups, assigned)
                ]
                rank = (
                    max(score[0] for score in scores),
                    sum(score[1] for score in scores),
                )
                if best_assignment is None or rank < best_assignment[0]:
                    best_assignment = (rank, groups, assigned, scores)
        if best_assignment is None:
            return None
        _, meal_groups, assigned_attractions, route_scores = best_assignment

        for day_index, (group, attraction, score) in enumerate(
            zip(meal_groups, assigned_attractions, route_scores)
        ):
            selected_attractions = [attraction]
            ordered_group = score[2]
            day_meals = [
                Meal(
                    type=meal_type,
                    name=str(record.get("name") or ""),
                    address=str(record.get("address") or ""),
                    location=cls._parse_poi_location(record),
                    description="可按当日路线就近用餐，建议以店内实际菜单为准。",
                    estimated_cost=cls._meal_cost(record, budget_limit),
                    poi_id=str(record.get("poi_id") or ""),
                )
                for meal_type, record in zip(required_types, ordered_group)
            ]
            days.append(DayPlan(
                date=(start + timedelta(days=day_index)).isoformat(),
                day_index=day_index,
                description="围绕同一片区安排景点与三餐，减少往返。",
                transportation=request.transportation,
                accommodation=request.accommodation,
                hotel=Hotel(
                    name=str(selected_hotel.get("name") or ""),
                    address=str(selected_hotel.get("address") or ""),
                    location=selected_hotel_location,
                    price_range=str(selected_hotel.get("cost") or "到店询价"),
                    rating=str(selected_hotel.get("rating") or ""),
                    distance="当日路线起终点",
                    type=str(selected_hotel.get("type") or request.accommodation),
                    poi_id=str(selected_hotel.get("poi_id") or ""),
                ),
                attractions=[
                    Attraction(
                        name=str(attraction.get("name") or ""),
                        address=str(attraction.get("address") or ""),
                        location=cls._parse_poi_location(attraction),
                        visit_duration=120,
                        description=str(attraction.get("type") or "高德 POI 景点"),
                        poi_id=str(attraction.get("poi_id") or ""),
                    )
                    for attraction in selected_attractions
                ],
                meals=day_meals,
            ))

        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=[],
            overall_suggestions="按每天同片区顺序出行；餐厅均不重复，出发前请确认营业时间。",
        )

    @staticmethod
    def _weather_for_travel_dates(
        weather_info: list[WeatherInfo],
        request: TripRequest,
    ) -> list[WeatherInfo]:
        """仅保留旅行日期内的高德预报，绝不把本日天气改标为旅行日天气。

        高德的预报从查询当天开始返回有限天数。旅行日期超出预报窗口时，
        只展示可获得的旅行日预报，避免向用户展示与本次行程无关的“今天”。
        """
        try:
            start = date.fromisoformat(request.start_date)
        except ValueError:
            print(f"天气日期筛选跳过: 无法解析旅行开始日期 {request.start_date!r}")
            return []

        travel_dates = {
            (start + timedelta(days=index)).isoformat()
            for index in range(request.travel_days)
        }
        selected: list[WeatherInfo] = []
        seen_dates: set[str] = set()
        for item in weather_info:
            if item.date not in travel_dates or item.date in seen_dates:
                continue
            selected.append(item)
            seen_dates.add(item.date)

        ignored_dates = [item.date for item in weather_info if item.date not in travel_dates]
        if ignored_dates:
            print(
                "天气已按旅行日期筛选: "
                f"旅行日={sorted(travel_dates)}; 忽略非旅行日预报={ignored_dates}"
            )
        if not selected and weather_info:
            print(
                "高德预报未覆盖旅行日期，天气区块将不展示；"
                f"旅行日={sorted(travel_dates)}"
            )
        return selected

    @staticmethod
    def _complete_weather_for_travel_dates(
        weather_info: list[WeatherInfo],
        request: TripRequest,
        city_center: Optional[Location] = None,
    ) -> list[WeatherInfo]:
        """保留已有旅行日预报，并且只精确补查缺失的旅行日期。"""
        selected = TripPlannerAgent._weather_for_travel_dates(weather_info, request)
        start = date.fromisoformat(request.start_date)
        ordered_dates = [
            (start + timedelta(days=index)).isoformat()
            for index in range(request.travel_days)
        ]
        weather_by_date = {item.date: item for item in selected}
        missing_dates = [item for item in ordered_dates if item not in weather_by_date]
        if not missing_dates:
            return [weather_by_date[item] for item in ordered_dates]

        from ..services.amap_service import get_amap_service

        service = get_amap_service()
        for missing_date in missing_dates:
            try:
                print(f"天气缺失日期精确补查: 城市={request.city}; 日期={missing_date}")
                weather_by_date[missing_date] = service.get_weather_for_date(
                    request.city,
                    missing_date,
                    location=city_center,
                )
            except Exception as error:
                print(
                    f"天气缺失日期补查失败: 日期={missing_date}; "
                    f"{type(error).__name__}: {error}"
                )
        return [weather_by_date[item] for item in ordered_dates if item in weather_by_date]

    @staticmethod
    def _enrich_attraction_images(
        plan: TripPlan,
        city_center: Optional[Location] = None,
        radius_km: Optional[float] = None,
        target_adcode: Optional[str] = None,
        amap_city: Optional[str] = None,
    ) -> TripPlan:
        """用高德 POI 校正景点坐标并补齐图片。

        一个城市只请求一次 POI 列表，再按景点名称匹配，避免为每个景点
        单独请求高德接口导致规划链路被网络 IO 拖慢。

        当提供 ``city_center`` 时，额外执行越界重查：坐标偏离目标城市的景点
        （如深圳计划里混入的北京景点）会被替换为高德在该城市搜到的真实 POI，
        候选耗尽则丢弃该景点，最终交由 ``validate_trip_plan`` 兜底。
        """
        # 历史计划可能只有“第1天早餐”等占位餐饮；先从 Chroma 回填真实餐馆，
        # 这条路径不依赖高德图片 API，确保已有缓存坐标能进入每日路线。
        TripPlannerAgent._enrich_meal_pois(
            plan,
            city_center=city_center,
            radius_km=radius_km,
            target_adcode=target_adcode,
        )

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

        # 标准化城市名给高德，避免区县名搜出外地结果；区县 adcode 负责二次硬过滤。
        city_normalized = amap_city or _normalize_city_for_amap(plan.city)
        district_keyword = _district_keyword(plan.city)
        broad_keyword = f"{district_keyword} 景点" if district_keyword else "景点"
        try:
            # 泛搜索只用于图片兜底，禁止用它的模糊结果覆盖景点坐标。
            pois = photo_service.search_pois(
                broad_keyword,
                city=city_normalized,
                offset=min(20, max(10, len(attractions) * 3)),
            )
        except Exception as error:
            print(f"⚠️ 高德泛搜索跳过: {type(error).__name__}: {error}")
            pois = []

        def normalize(value: str) -> str:
            return "".join(str(value or "").split()).lower()

        def poi_in_scope(poi: dict) -> bool:
            if not isinstance(poi, dict):
                return False
            poi_adcode = str(poi.get("adcode") or "").strip()
            if target_adcode and poi_adcode:
                return poi_adcode == target_adcode
            if not city_center or not radius_km:
                # 历史图片补齐接口未传入地理基准时，保持原有补图行为。
                return True
            location = TripPlannerAgent._parse_poi_location(poi)
            return bool(
                location
                and city_center
                and radius_km
                and is_within_city(location, city_center, radius_km)
            )

        normalized_pois = [
            (normalize(poi.get("name", "")), poi)
            for poi in pois
            if poi_in_scope(poi)
        ]
        exact_poi_cache: dict[tuple[str, str], list[dict]] = {}

        def exact_poi_for(name: str) -> Optional[dict]:
            """按景点名称精确查询，返回名称完全相同的 POI。"""
            cities = [_normalize_city_for_amap(plan.city)]
            # 已标准化的城市无需额外添加（旧逻辑是坪山→深圳兜底，现在统一走 normalize）
            normalized_name = normalize(name)
            for city in cities:
                cache_key = (normalized_name, city)
                if cache_key not in exact_poi_cache:
                    try:
                        exact_poi_cache[cache_key] = photo_service.search_pois(
                            name,
                            city=city,
                            offset=20,
                        )
                    except Exception as error:
                        print(
                            f"⚠️ 高德景点精确查询跳过({name}, {city}): "
                            f"{type(error).__name__}: {error}"
                        )
                        exact_poi_cache[cache_key] = []
                exact_match = next(
                    (
                        poi for poi in exact_poi_cache[cache_key]
                        if normalize(poi.get("name", "")) == normalized_name
                        and poi_in_scope(poi)
                    ),
                    None,
                )
                if exact_match:
                    return exact_match
            return None

        # 多个景点并发查询，避免 12 个景点串行等待网络超时，导致前端继续使用旧坐标。
        unique_names = list(dict.fromkeys(attraction.name for attraction in attractions))
        exact_matches: dict[str, Optional[dict]] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(unique_names))) as executor:
            futures = {
                executor.submit(exact_poi_for, name): name
                for name in unique_names
            }
            for future, name in ((future, futures[future]) for future in futures):
                try:
                    exact_matches[name] = future.result()
                except Exception as error:
                    print(
                        f"⚠️ 高德景点精确查询失败({name}): "
                        f"{type(error).__name__}: {error}"
                    )
                    exact_matches[name] = None

        for attraction in attractions:
            attraction_name = normalize(attraction.name)
            if not attraction_name:
                continue
            exact_match = exact_matches.get(attraction.name)
            if exact_match:
                TripPlannerAgent._apply_poi_data(attraction, exact_match)
                photos = AmapPhotoService._extract_photos(exact_match)
                if photos and not TripPlannerAgent._is_amap_image_url(attraction.image_url):
                    attraction.image_url = photos[0]["url"]
                continue

            # 精确查询无结果时，只允许泛搜索命中“名称完全相同”的 POI，
            # 避免把模型景点坐标替换成附近的其他地点。
            exact_from_broad = next(
                (poi for poi_name, poi in normalized_pois if poi_name == attraction_name),
                None,
            )
            if exact_from_broad:
                TripPlannerAgent._apply_poi_data(attraction, exact_from_broad)
                photos = AmapPhotoService._extract_photos(exact_from_broad)
                if photos and not TripPlannerAgent._is_amap_image_url(attraction.image_url):
                    attraction.image_url = photos[0]["url"]

        # 越界重查：坐标校正后仍偏离目标城市的景点，多半是模型套用了其他城市的坐标
        # （如深圳计划里的北京故宫）。用高德在该城市搜到的真实 POI 整条替换，
        # 候选池耗尽则丢弃，避免把外地坐标画到地图上。
        if city_center is not None and radius_km and radius_km > 0:
            TripPlannerAgent._repair_out_of_city_attractions(
                plan, pois, city_center, radius_km, normalize, target_adcode
            )

        # 酒店和餐馆也可能只有名称没有坐标，按类别补一次高德 POI 坐标。
        route_targets = {
            "酒店": [
                day.hotel
                for day in plan.days
                if day.hotel and day.hotel.location is None
            ],
            "餐厅": [
                meal
                for day in plan.days
                for meal in day.meals
                if meal.location is None
            ],
        }
        for keywords, targets in route_targets.items():
            if not targets:
                continue
            try:
                scoped_keywords = (
                    f"{district_keyword} {keywords}" if district_keyword else keywords
                )
                pois = photo_service.search_pois(
                    scoped_keywords,
                    city=city_normalized,
                    offset=min(20, max(10, len(targets) * 3)),
                )
            except Exception as error:
                print(f"⚠️ 高德{keywords}坐标补齐跳过: {type(error).__name__}: {error}")
                continue
            normalized_pois = [
                (normalize(poi.get("name", "")), poi)
                for poi in pois
                if poi_in_scope(poi)
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

        # 酒店/餐厅坐标可选：仍越界的直接清空，避免把外地点位画到地图上
        # （景点是必填坐标，已在越界重查里替换，这里只处理可选点位）。
        if city_center is not None and radius_km and radius_km > 0:
            for targets in route_targets.values():
                for target in targets:
                    location = getattr(target, "location", None)
                    if location is not None and not is_within_city(location, city_center, radius_km):
                        target.location = None
        return plan

    @staticmethod
    def _enrich_meal_pois(
        plan: TripPlan,
        city_center: Optional[Location] = None,
        radius_km: Optional[float] = None,
        target_adcode: Optional[str] = None,
    ) -> TripPlan:
        """把历史计划中的餐饮占位项回填为 Chroma 真实餐馆 POI。"""
        meals = [meal for day in plan.days for meal in day.meals]
        if not meals:
            return plan
        # 新生成的确定性计划已经使用本轮 POI 证据，名称、ID、坐标和地址均
        # 完整；不应再次启动一次 Chroma 嵌入查询。该查询只服务于历史计划
        # 的占位餐饮回填，并且在 Chroma 冷启动时会浪费数十秒。
        if all(meal.poi_id and meal.location and meal.address for meal in meals):
            return plan
        try:
            from ..services.poi_vector_store import get_poi_vector_store

            store = get_poi_vector_store()
            if not store:
                return plan
            candidates = store.search(
                query=f"{plan.city} 餐馆 美食",
                city=_normalize_city_for_amap(plan.city),
                limit=max(20, len(meals) * 3),
                adcode=target_adcode,
                poi_group="meal",
            )
        except Exception as error:
            print(f"Chroma 餐馆回填跳过: {type(error).__name__}: {error}")
            return plan

        def normalise(value: object) -> str:
            return "".join(str(value or "").split()).lower()

        def in_scope(candidate: dict) -> bool:
            if not city_center or not radius_km:
                return True
            location = TripPlannerAgent._parse_poi_location({
                "location": f"{candidate.get('longitude')},{candidate.get('latitude')}"
            })
            return bool(location and is_within_city(location, city_center, radius_km))

        candidates = [candidate for candidate in candidates if in_scope(candidate)]
        if not candidates:
            return plan

        used_ids: set[str] = set()
        for meal in meals:
            if meal.poi_id and meal.location:
                continue
            meal_name = normalise(meal.name)
            candidate = next(
                (
                    item for item in candidates
                    if item.get("poi_id") not in used_ids
                    and (
                        str(item.get("poi_id") or "") == str(meal.poi_id or "")
                        or (meal_name and meal_name in normalise(item.get("name")))
                    )
                ),
                None,
            )
            if candidate is None:
                candidate = next(
                    (
                        item for item in candidates
                        if item.get("poi_id") not in used_ids
                    ),
                    candidates[0],
                )
            poi_id = str(candidate.get("poi_id") or "")
            if not poi_id:
                continue
            used_ids.add(poi_id)
            location = TripPlannerAgent._parse_poi_location({
                "location": f"{candidate.get('longitude')},{candidate.get('latitude')}"
            })
            if location is None:
                continue
            meal.name = str(candidate.get("name") or meal.name)
            meal.address = str(candidate.get("address") or meal.address or "")
            meal.location = location
            meal.poi_id = poi_id
            if not meal.description or meal.description in {
                "午餐推荐", "晚餐推荐", "早餐推荐", "当地特色早餐", "当地特色餐饮",
            }:
                meal.description = str(candidate.get("type") or "高德餐饮 POI")
            if not meal.estimated_cost:
                match = re.search(r"\d+(?:\.\d+)?", str(candidate.get("cost") or ""))
                if match:
                    meal.estimated_cost = int(float(match.group()))
            print(
                f"Chroma 餐馆回填: {meal.type}={meal.name} | "
                f"{meal.address} | {location.longitude},{location.latitude}"
            )
        return plan

    @staticmethod
    def _repair_out_of_city_attractions(
        plan: TripPlan,
        pois: list,
        city_center: Location,
        radius_km: float,
        normalize,
        target_adcode: Optional[str] = None,
    ) -> None:
        """把坐标越界的景点替换为高德在该城市搜到的真实 POI，候选耗尽则丢弃。

        替换源是泛搜索(``城市 + 景点``)返回的、坐标落在城内的真实 POI，
        天然与目标城市一致；每个候选只用一次，避免重复景点。
        """
        used_names = {
            normalize(attraction.name)
            for day in plan.days
            for attraction in day.attractions
        }
        replacement_pool: list[dict] = []
        for poi in pois:
            if not isinstance(poi, dict):
                continue
            location = TripPlannerAgent._parse_poi_location(poi)
            poi_adcode = str(poi.get("adcode") or "").strip()
            if target_adcode and poi_adcode:
                in_scope = poi_adcode == target_adcode
            else:
                in_scope = bool(
                    location and is_within_city(location, city_center, radius_km)
                )
            if location is None or not in_scope:
                continue
            poi_name = normalize(poi.get("name", ""))
            if not poi_name or poi_name in used_names:
                continue
            used_names.add(poi_name)
            replacement_pool.append(poi)

        pool_iter = iter(replacement_pool)
        for index, day in enumerate(plan.days, start=1):
            kept: list[Attraction] = []
            for attraction in day.attractions:
                if is_within_city(attraction.location, city_center, radius_km):
                    kept.append(attraction)
                    continue
                replacement = next(pool_iter, None)
                if replacement is None:
                    print(
                        f"⚠️ 第{index}天景点“{attraction.name}”坐标越界且无城内候选，已丢弃"
                    )
                    continue
                print(
                    f"⚠️ 第{index}天景点“{attraction.name}”坐标越界，"
                    f"替换为“{replacement.get('name')}”"
                )
                TripPlannerAgent._overwrite_attraction_from_poi(
                    attraction, replacement, plan.city
                )
                kept.append(attraction)
            day.attractions = kept

    @staticmethod
    def _overwrite_attraction_from_poi(
        attraction: Attraction, poi: dict, city: str
    ) -> None:
        """用城内 POI 整条覆盖越界景点，保证名称/地址/坐标/图片彼此一致。

        模型原本的描述是针对外地景点写的，替换坐标后必须一并清掉，
        否则会出现“名字是深圳景点、简介却在讲北京”的错位。
        """
        TripPlannerAgent._apply_poi_data(attraction, poi)
        poi_type = str(poi.get("type") or "").split(";")[0].strip()
        attraction.description = poi_type or f"{city}的推荐景点"
        attraction.category = "景点"
        attraction.rating = None
        attraction.ticket_price = 0
        attraction.photos = []
        photos = AmapPhotoService._extract_photos(poi)
        attraction.image_url = photos[0]["url"] if photos else None

    @staticmethod
    def _apply_poi_data(attraction: Attraction, poi: dict) -> None:
        """将高德 POI 的权威名称、地址、编号和 GCJ-02 坐标写回景点。"""
        location = TripPlannerAgent._parse_poi_location(poi)
        if location:
            attraction.location = location
        poi_id = str(poi.get("id") or "")
        if poi_id:
            attraction.poi_id = poi_id
        poi_name = str(poi.get("name") or "").strip()
        if poi_name:
            attraction.name = poi_name
        poi_address = str(poi.get("address") or "").strip()
        if poi_address:
            attraction.address = poi_address

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
        vector_pois: Optional[list[dict]] = None,
    ) -> str:
        """构建规划任务；POI 候选由 search_poi Observation 按需提供。"""
        del vector_pois
        query = f"""请根据以下信息生成{request.city}的{request.travel_days}天旅行计划:

**基本信息:**
- 城市: {request.city}
- 日期: {request.start_date} 至 {request.end_date}
- 天数: {request.travel_days}天
- 交通方式: {request.transportation}
        - 住宿: {request.accommodation}
- 偏好: {', '.join(request.preferences) if request.preferences else '无'}
"""
        try:
            start = date.fromisoformat(request.start_date)
            daily_schedule = "\n".join(
                f"- 第{index + 1}天: date={(start + timedelta(days=index)).isoformat()}；"
                "必须在该 day 的 meals 中安排 breakfast、lunch、dinner"
                for index in range(request.travel_days)
            )
            query += (
                "\n**每日计划必须覆盖以下日期（餐馆按所在 day 写入 day.meals）:**\n"
                f"{daily_schedule}\n"
            )
        except ValueError:
            # 请求模型通常已保证日期格式；异常时交给最终 Validator 报告。
            pass
        district_keyword = _district_keyword(request.city)
        if district_keyword:
            query += (
                f"\n**硬性目标范围:** 仅限{request.city}（{district_keyword}区/新区），"
                "不得使用深圳其他行政区的景点、酒店或餐厅。\n"
            )
        if request.current_plan and (request.change_set or request.change_request):
            auto_replan = bool(
                request.change_set
                and any(item.operation == "full_replan" for item in request.change_set.operations)
            )
            replan_rules = (
                "1. 保持目的地和日期不变，主动优化每日节奏、景点组合、餐饮和路线。\n"
                "2. 直接完成规划，不要向用户追问。\n"
                "3. 返回完整的旅行计划 JSON。"
                if auto_replan
                else "1. 只修改用户明确要求的日期、景点、餐饮、酒店、交通或预算。\n"
                "2. 未被要求修改的日期和内容必须保留。\n"
                "3. 返回完整的旅行计划 JSON，不能只返回修改片段。"
            )
            query += f"""
**当前旅行计划(JSON):**
{json.dumps(request.current_plan, ensure_ascii=False)}

**定向修改要求:**
{request.change_request}

**结构化 ChangeSet:**
{request.change_set.model_dump_json() if request.change_set else '无'}

**定向修改规则:**
{replan_rules}
"""
        if request.free_text_input:
            query += f"\n**额外要求:** {request.free_text_input}"
        if preference and preference.prompt and preference.prompt != request.free_text_input:
            query += f"\n**用户偏好:** {preference.prompt}"

        max_leg_km = getattr(
            get_settings(), "planner_max_daily_route_leg_km", 7.0
        )
        query += (
            "\n\n**路线顺序要求:** 同一天的景点必须位于彼此相近的片区，并按地理邻近顺序安排；"
            "不得在同一天内先去城区东侧、再去西侧、随后又回到东侧。"
            f"早餐、午餐和晚餐必须与相邻景点同片区；相邻节点直线距离不得超过 {max_leg_km:g} 公里。"
            "每天必须选择一个带真实 POI ID、地址和坐标的酒店，并按“酒店出发→当日节点→返回酒店”闭环安排。"
            "同一餐馆 POI 整个行程只能使用一次，禁止重复同一美食城。"
            "\n\n**Draft 最小契约:** 顶层包含 city、start_date、end_date、days、weather_info、"
            "overall_suggestions；每个 day 包含 date、day_index、description、transportation、"
            "accommodation、hotel、attractions、meals。hotel 必须包含 name、address、location、"
            "price_range、type、poi_id。景点必须包含 name、address、location、"
            "visit_duration、description、poi_id。每餐必须包含 type、name、address、location、"
            "description、estimated_cost、poi_id。"
        )

        return query

    @staticmethod
    def _geo_distance_squared(left: Location, right: Location) -> float:
        """用于同城 POI 排序的轻量近似距离；无需发起额外路线请求。"""
        latitude_scale = math.cos(math.radians((left.latitude + right.latitude) / 2))
        longitude_delta = (left.longitude - right.longitude) * latitude_scale
        latitude_delta = left.latitude - right.latitude
        return longitude_delta * longitude_delta + latitude_delta * latitude_delta

    @classmethod
    def _order_day_attractions_by_proximity(cls, plan: TripPlan) -> TripPlan:
        """从早餐（或酒店）出发，以近邻顺序排列当日景点，避免无意义折返。"""
        for day in plan.days:
            remaining = [item for item in day.attractions if item.location is not None]
            without_location = [item for item in day.attractions if item.location is None]
            if len(remaining) < 2:
                continue
            breakfast = next((meal for meal in day.meals if meal.type == "breakfast"), None)
            current = (
                breakfast.location if breakfast and breakfast.location else
                day.hotel.location if day.hotel and day.hotel.location else
                remaining[0].location
            )
            ordered = []
            while remaining:
                next_index = min(
                    range(len(remaining)),
                    key=lambda index: cls._geo_distance_squared(
                        current,
                        remaining[index].location,
                    ),
                )
                next_attraction = remaining.pop(next_index)
                ordered.append(next_attraction)
                current = next_attraction.location
            day.attractions = ordered + without_location
        return plan

    def _execute_change_set(
        self,
        plan: TripPlan,
        change_set: ChangeSet,
        request: TripRequest,
        vector_pois: list[dict],
        target_adcode: Optional[str],
    ) -> tuple[TripPlan, list[str]]:
        """执行 LLM 产生的白名单操作；任何操作失败都会阻止整次持久化。"""
        changes: list[str] = []
        for operation in change_set.operations:
            if operation.operation == "delete_attraction":
                removed = self._delete_attractions(plan, operation)
                if not removed:
                    raise ValueError("delete_attraction 没有匹配到任何景点")
                changes.append("移除 " + "、".join(removed))
                continue

            if operation.operation in {"replace_attraction", "add_attraction"}:
                target = operation.target
                query = ((target.name if target else None) or (target.semantic if target else None) or "").strip()
                if not query:
                    raise ValueError(f"{operation.operation} 缺少 target.name 或 target.semantic")
                poi = self._resolve_replacement_poi(request, query, vector_pois, target_adcode)
                if poi is None:
                    raise ValueError(f"在{request.city}范围内没有找到符合“{query}”的真实 POI")
                if operation.operation == "replace_attraction":
                    replaced = self._replace_attraction(plan, operation, poi)
                    if not replaced:
                        raise ValueError("replace_attraction 没有匹配到待替换景点")
                    changes.append(f"替换 {replaced} 为 {poi.get('name')}")
                else:
                    day_index = self._add_attraction(plan, operation, poi)
                    changes.append(f"在第{day_index + 1}天添加 {poi.get('name')}")
                continue

            if operation.operation == "update_day":
                day_index = operation.selector.day_index if operation.selector else None
                if day_index is None or day_index >= len(plan.days):
                    raise ValueError("update_day 缺少有效的 selector.day_index")
                allowed = {"description", "transportation", "accommodation"}
                updated = []
                for field, value in operation.fields.items():
                    if field in allowed and isinstance(value, str):
                        setattr(plan.days[day_index], field, value)
                        updated.append(field)
                if not updated:
                    raise ValueError("update_day 没有可执行的白名单字段")
                changes.append(f"更新第{day_index + 1}天: {', '.join(updated)}")
                continue

            raise ValueError(f"局部执行器不支持操作: {operation.operation}")
        return plan, changes

    @staticmethod
    def _operation_matches_attraction(attraction: Attraction, operation: ChangeOperation) -> bool:
        selector = operation.selector
        if selector is None:
            return False
        searchable = "".join(
            "|".join((attraction.name, attraction.description, attraction.category or "")).split()
        ).lower()
        checks = []
        if selector.name:
            checks.append("".join(selector.name.split()).lower() in searchable)
        if selector.semantic:
            checks.append("".join(selector.semantic.split()).lower() in searchable)
        return bool(checks) and all(checks)

    @classmethod
    def _delete_attractions(cls, plan: TripPlan, operation: ChangeOperation) -> list[str]:
        removed: list[str] = []
        for day in plan.days:
            retained = []
            for attraction in day.attractions:
                day_matches = (
                    operation.selector is None
                    or operation.selector.day_index is None
                    or operation.selector.day_index == day.day_index
                )
                if day_matches and cls._operation_matches_attraction(attraction, operation):
                    removed.append(attraction.name)
                else:
                    retained.append(attraction)
            day.attractions = retained
        return removed

    @classmethod
    def _replace_attraction(cls, plan: TripPlan, operation: ChangeOperation, poi: dict) -> str | None:
        for day in plan.days:
            for attraction in day.attractions:
                if cls._operation_matches_attraction(attraction, operation):
                    old_name = attraction.name
                    cls._overwrite_attraction_from_poi(attraction, poi, plan.city)
                    return old_name
        return None

    @classmethod
    def _add_attraction(cls, plan: TripPlan, operation: ChangeOperation, poi: dict) -> int:
        requested_index = operation.selector.day_index if operation.selector else None
        if requested_index is None:
            requested_index = min(range(len(plan.days)), key=lambda index: len(plan.days[index].attractions))
        if requested_index < 0 or requested_index >= len(plan.days):
            raise ValueError("add_attraction 的 selector.day_index 超出行程范围")
        location = cls._parse_poi_location(poi)
        if location is None:
            raise ValueError("新增 POI 缺少有效坐标")
        attraction = Attraction(
            name=str(poi.get("name") or ""),
            address=str(poi.get("address") or ""),
            location=location,
            visit_duration=120,
            description=str(poi.get("type") or "真实高德 POI"),
            poi_id=str(poi.get("id") or poi.get("poi_id") or ""),
        )
        plan.days[requested_index].attractions.append(attraction)
        return requested_index

    @staticmethod
    def _poi_as_amap_record(poi: dict) -> dict:
        """统一 Chroma 元数据与高德 REST POI 的字段，便于覆盖行程节点。"""
        result = dict(poi)
        if not result.get("id"):
            result["id"] = result.get("poi_id") or ""
        if not result.get("location"):
            longitude = result.get("longitude")
            latitude = result.get("latitude")
            if longitude is not None and latitude is not None:
                result["location"] = f"{longitude},{latitude}"
        return result

    @staticmethod
    def _poi_matches_target(poi: dict, target: str) -> bool:
        normalized_target = "".join((target or "").split()).lower()
        normalized_name = "".join(str(poi.get("name") or "").split()).lower()
        poi_type = str(poi.get("type") or "")
        if normalized_target == "大学":
            return "大学" in normalized_name or "高等院校" in poi_type
        return bool(normalized_target and normalized_target in normalized_name)

    @staticmethod
    def _rank_replacement_poi(poi: dict, target: str) -> int:
        """用高德名称和类型挑选地点主体，排除同名公交站、停车场等附属 POI。"""
        name = str(poi.get("name") or "")
        poi_type = str(poi.get("type") or "")
        target = (target or "").strip()
        score = 0
        if name == target:
            score += 80
        elif name.endswith(target):
            score += 50
        elif target in name:
            score += 30

        if "大学" in target:
            if "高等院校" in poi_type:
                score += 120
            elif "学校" in poi_type:
                score += 15
            if "大学" in name:
                score += 40
            if any(marker in f"{name}|{poi_type}" for marker in (
                "附属", "医院", "公交", "地铁", "停车", "酒店", "宾馆", "研究院",
            )):
                score -= 200
        return score

    def _resolve_replacement_poi(
        self,
        request: TripRequest,
        target: str,
        vector_pois: list[dict],
        target_adcode: Optional[str],
    ) -> Optional[dict]:
        """先从 Chroma 召回替换目标，缺失时只做一次高德 REST 精确搜索。"""
        def in_scope(poi: dict) -> bool:
            poi_adcode = str(poi.get("adcode") or "").strip()
            return not target_adcode or poi_adcode == target_adcode

        candidates = [
            self._poi_as_amap_record(poi)
            for poi in vector_pois
            if classify_poi_group(poi) == "attraction"
            and self._poi_matches_target(poi, target)
            and in_scope(poi)
        ]
        if not candidates:
            district_keyword = _district_keyword(request.city)
            keywords = f"{district_keyword} {target}" if district_keyword else target
            try:
                pois = get_amap_photo_service().search_pois(
                    keywords,
                    city=_normalize_city_for_amap(request.city),
                    offset=20,
                )
                candidates = [
                    self._poi_as_amap_record(poi)
                    for poi in pois
                    if classify_poi_group(poi) == "attraction"
                    and self._poi_matches_target(poi, target)
                    and in_scope(poi)
                ]
                print(
                    f"定向替换 POI 查询: 目标={target}; 城市={request.city}; "
                    f"候选={len(candidates)}"
                )
            except Exception as error:
                print(f"⚠️ 定向替换 POI 查询失败: {type(error).__name__}: {error}")

        if not candidates:
            return None
        return max(candidates, key=lambda poi: self._rank_replacement_poi(poi, target))

    @staticmethod
    def _retrieve_cached_pois(
        request: TripRequest,
        preference: Optional[Preference],
        adcode: Optional[str] = None,
        amap_city: Optional[str] = None,
    ) -> list[dict]:
        """先按景点、酒店、餐馆三大类从 Chroma 召回，天气和路线仍实时查询。"""
        try:
            from ..services.poi_vector_store import get_poi_vector_store

            store = get_poi_vector_store()
            if not store:
                return []
            query = " ".join(
                value for value in (
                    request.city,
                    " ".join(request.preferences),
                    request.change_request or "",
                    request.free_text_input or "",
                    preference.prompt if preference else "",
                ) if value
            )
            city = amap_city or _normalize_city_for_amap(request.city)
            results = []
            group_queries = {
                "attraction": f"{query} 景点",
                "hotel": f"{query} 酒店住宿",
                "meal": f"{query} 餐馆美食",
            }
            for group, group_query in group_queries.items():
                group_results = store.search(
                    query=group_query,
                    # 写入 POI 时使用与高德 citylimit 一致的地级市键，
                    # 例如“深圳坪山”写入“深圳”，检索必须使用同一键。
                    city=city,
                    limit=get_settings().poi_vector_top_k,
                    adcode=adcode,
                    poi_group=group,
                )
                results.extend(group_results)
            # 同一 POI 可能由多次高德搜索写入，保持候选稳定且不重复。
            deduplicated = list({
                (poi.get("poi_id") or poi.get("name"), poi.get("poi_group")): poi
                for poi in results
            }.values())
            print(
                f"Chroma POI 分大类召回: 城市={request.city}; "
                f"景点={sum(p.get('poi_group') == 'attraction' for p in deduplicated)}; "
                f"酒店={sum(p.get('poi_group') == 'hotel' for p in deduplicated)}; "
                f"餐馆={sum(p.get('poi_group') == 'meal' for p in deduplicated)}"
            )
            return deduplicated
        except Exception as error:
            print(f"⚠️ Chroma POI 检索跳过: {type(error).__name__}: {error}")
            return []

# 全局单 Agent 实例
_trip_planner_agent = None


def get_trip_planner_agent() -> TripPlannerAgent:
    """获取单 Agent 旅行规划系统实例。"""
    global _trip_planner_agent

    if _trip_planner_agent is None:
        _trip_planner_agent = TripPlannerAgent()

    return _trip_planner_agent
