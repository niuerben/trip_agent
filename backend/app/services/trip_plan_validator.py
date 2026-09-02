"""旅行计划的业务级校验。"""

from datetime import date, timedelta
from math import asin, cos, radians, sin, sqrt
from dataclasses import asdict, dataclass
from typing import Optional

from ..config import get_settings
from ..models.schemas import Location, TripPlan, TripRequest

_EARTH_RADIUS_KM = 6371.0088


class TripPlanValidationError(ValueError):
    """旅行计划未满足业务约束。"""


@dataclass(frozen=True)
class ValidationIssue:
    """可反馈给规划 Agent 的结构化缺陷。"""

    code: str
    message: str
    day_index: Optional[int] = None
    entity_type: Optional[str] = None
    entity_name: Optional[str] = None

    def model_dump(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value is not None}


def haversine_km(a: Location, b: Location) -> float:
    """计算两个 GCJ-02 坐标之间的球面距离(公里)。

    高德坐标是 GCJ-02，与 WGS-84 存在偏移，但偏移量在百米量级，
    对"是否跨城/跨省"这种上百公里的判定不构成影响，直接用球面公式即可。
    """
    lon1, lat1, lon2, lat2 = map(
        radians, (a.longitude, a.latitude, b.longitude, b.latitude)
    )
    d_lon = lon2 - lon1
    d_lat = lat2 - lat1
    h = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(h))


def is_within_city(
    location: Optional[Location],
    city_center: Optional[Location],
    radius_km: float,
) -> bool:
    """判断坐标是否落在城市中心的允许半径内。

    缺少坐标或城市中心(高德解析失败)时返回 True，避免因基准缺失误杀计划——
    越界拦截是"有据可依才拦"，宁可放过也不误伤。
    """
    if location is None or city_center is None:
        return True
    return haversine_km(location, city_center) <= radius_km


def collect_trip_plan_issues(
    plan: TripPlan,
    request: TripRequest,
    city_center: Optional[Location] = None,
    radius_km: Optional[float] = None,
    require_enriched_locations: bool = False,
) -> list[ValidationIssue]:
    """返回结构化缺陷，供 ReAct 循环观察并定向修复。"""
    issues: list[ValidationIssue] = []

    def add(code: str, message: str, **context) -> None:
        issues.append(ValidationIssue(code=code, message=message, **context))

    if plan.city != request.city:
        add("CITY_MISMATCH", f"城市不一致: {plan.city} != {request.city}")
    if plan.start_date != request.start_date:
        add("START_DATE_MISMATCH", f"开始日期不一致: {plan.start_date} != {request.start_date}")
    if plan.end_date != request.end_date:
        add("END_DATE_MISMATCH", f"结束日期不一致: {plan.end_date} != {request.end_date}")
    if len(plan.days) != request.travel_days:
        add("DAY_COUNT_MISMATCH", f"天数不一致: {len(plan.days)} != {request.travel_days}")

    try:
        start = date.fromisoformat(request.start_date)
        expected_dates = {
            (start + timedelta(days=index)).isoformat()
            for index in range(request.travel_days)
        }
        actual_dates = {day.date for day in plan.days}
        if actual_dates != expected_dates:
            add("TRAVEL_DATES_INCOMPLETE", "每日日期未覆盖完整旅行区间")
    except ValueError:
        add("REQUEST_DATE_INVALID", "请求日期格式无效")

    required_meals = {
        item.strip()
        for item in get_settings().required_meal_types.split(",")
        if item.strip()
    }
    used_meal_pois: dict[str, tuple[int, str]] = {}
    for index, day in enumerate(plan.days):
        if day.hotel is None:
            add(
                "HOTEL_MISSING",
                f"第{index + 1}天没有酒店，路线无法从酒店出发并返回酒店",
                day_index=index,
                entity_type="hotel",
            )
        else:
            if not day.hotel.poi_id:
                add(
                    "HOTEL_POI_MISSING",
                    f"酒店“{day.hotel.name}”缺少真实高德 POI ID",
                    day_index=index,
                    entity_type="hotel",
                    entity_name=day.hotel.name,
                )
            if not day.hotel.address:
                add(
                    "HOTEL_ADDRESS_MISSING",
                    f"酒店“{day.hotel.name}”缺少地址",
                    day_index=index,
                    entity_type="hotel",
                    entity_name=day.hotel.name,
                )
            if day.hotel.location is None:
                add(
                    "HOTEL_LOCATION_MISSING",
                    f"酒店“{day.hotel.name}”缺少坐标",
                    day_index=index,
                    entity_type="hotel",
                    entity_name=day.hotel.name,
                )
        if not day.attractions:
            add("ATTRACTIONS_MISSING", f"第{index + 1}天没有景点安排", day_index=index)
        for attraction in day.attractions:
            if not attraction.poi_id:
                add(
                    "ATTRACTION_POI_MISSING",
                    f"景点“{attraction.name}”缺少真实高德 POI ID",
                    day_index=index,
                    entity_type="attraction",
                    entity_name=attraction.name,
                )

        meal_types = {meal.type for meal in day.meals}
        for missing_type in sorted(required_meals - meal_types):
            add(
                "MEAL_TYPE_MISSING",
                f"第{index + 1}天缺少 {missing_type}",
                day_index=index,
                entity_type="meal",
                entity_name=missing_type,
            )
        for meal in day.meals:
            context = {
                "day_index": index,
                "entity_type": "meal",
                "entity_name": meal.name,
            }
            if not meal.poi_id:
                add("MEAL_POI_MISSING", f"餐饮“{meal.name}”缺少真实高德 POI ID", **context)
            if not meal.address:
                add("MEAL_ADDRESS_MISSING", f"餐饮“{meal.name}”缺少地址", **context)
            if not meal.description:
                add("MEAL_DISH_MISSING", f"餐饮“{meal.name}”缺少推荐饭菜", **context)
            if meal.estimated_cost <= 0:
                add("MEAL_PRICE_MISSING", f"餐饮“{meal.name}”缺少人均价格", **context)
            if require_enriched_locations and meal.location is None:
                add("MEAL_LOCATION_MISSING", f"餐饮“{meal.name}”缺少坐标", **context)
            if meal.poi_id:
                previous = used_meal_pois.get(meal.poi_id)
                if previous:
                    previous_day, previous_name = previous
                    add(
                        "MEAL_POI_DUPLICATE",
                        f"餐饮“{meal.name}”与第{previous_day + 1}天的“{previous_name}”重复，"
                        "请更换为其他真实餐馆",
                        **context,
                    )
                else:
                    used_meal_pois[meal.poi_id] = (index, meal.name)

        # 以实际展示顺序检查当日相邻节点，拦截“早餐在西边、景点在东边、午餐又回西边”
        # 这类虽然 POI 真实但体验很差的计划。每天必须从酒店出发并返回同一酒店，
        # 但不同天之间不额外绘制跨日连线。
        breakfast = [meal for meal in day.meals if meal.type == "breakfast"]
        lunch = [meal for meal in day.meals if meal.type == "lunch"]
        dinner = [meal for meal in day.meals if meal.type == "dinner"]
        other_meals = [meal for meal in day.meals if meal.type not in {"breakfast", "lunch", "dinner"}]
        attractions = list(day.attractions)
        split = (len(attractions) + 1) // 2
        route_entities = [
            *([day.hotel] if day.hotel else []),
            *breakfast,
            *attractions[:split],
            *lunch,
            *attractions[split:],
            *dinner,
            *other_meals,
        ]
        if day.hotel:
            route_entities.append(day.hotel)
        max_leg_km = get_settings().planner_max_daily_route_leg_km
        for origin, destination in zip(route_entities, route_entities[1:]):
            origin_location = getattr(origin, "location", None)
            destination_location = getattr(destination, "location", None)
            if origin_location is None or destination_location is None:
                continue
            distance = haversine_km(origin_location, destination_location)
            if distance > max_leg_km:
                add(
                    "ROUTE_LEG_TOO_LONG",
                    f"第{index + 1}天“{getattr(origin, 'name', '上一站')}”到"
                    f"“{getattr(destination, 'name', '下一站')}”直线约{distance:.1f}公里，"
                    f"超过{max_leg_km:.0f}公里；请将餐饮或景点换到同一片区",
                    day_index=index,
                    entity_type="route",
                    entity_name=getattr(destination, "name", None),
                )

    if city_center is not None:
        effective_radius = radius_km if radius_km and radius_km > 0 else 150.0
        for index, day in enumerate(plan.days):
            entities = [*day.attractions, *day.meals]
            if day.hotel:
                entities.append(day.hotel)
            for entity in entities:
                location = getattr(entity, "location", None)
                if location is None or is_within_city(location, city_center, effective_radius):
                    continue
                distance = haversine_km(location, city_center)
                name = getattr(entity, "name", "未命名地点")
                add(
                    "POI_OUT_OF_SCOPE",
                    f"第{index + 1}天“{name}”坐标偏离{plan.city}约{distance:.0f}公里",
                    day_index=index,
                    entity_name=name,
                )
    return issues


def validate_trip_plan(
    plan: TripPlan,
    request: TripRequest,
    city_center: Optional[Location] = None,
    radius_km: Optional[float] = None,
    require_enriched_locations: bool = False,
) -> TripPlan:
    """最终交付闸门；任何结构化缺陷都会阻止计划返回。"""
    issues = collect_trip_plan_issues(
        plan,
        request,
        city_center,
        radius_km,
        require_enriched_locations,
    )
    if issues:
        raise TripPlanValidationError("；".join(issue.message for issue in issues))
    return plan
