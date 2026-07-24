"""旅行计划的业务级校验。"""

from datetime import date, timedelta

from ..models.schemas import TripPlan, TripRequest


class TripPlanValidationError(ValueError):
    """旅行计划未满足业务约束。"""


def validate_trip_plan(plan: TripPlan, request: TripRequest) -> TripPlan:
    """校验并返回旅行计划，阻止明显不一致的数据进入前端和数据库。"""
    errors: list[str] = []

    if plan.city != request.city:
        errors.append(f"城市不一致: {plan.city} != {request.city}")
    if plan.start_date != request.start_date:
        errors.append(f"开始日期不一致: {plan.start_date} != {request.start_date}")
    if plan.end_date != request.end_date:
        errors.append(f"结束日期不一致: {plan.end_date} != {request.end_date}")
    if len(plan.days) != request.travel_days:
        errors.append(
            f"天数不一致: {len(plan.days)} != {request.travel_days}"
        )

    try:
        start = date.fromisoformat(request.start_date)
        expected_dates = {
            (start + timedelta(days=index)).isoformat()
            for index in range(request.travel_days)
        }
        actual_dates = {day.date for day in plan.days}
        if actual_dates != expected_dates:
            errors.append("每日日期未覆盖完整旅行区间")
    except ValueError:
        errors.append("请求日期格式无效")

    for index, day in enumerate(plan.days, start=1):
        if not day.attractions:
            errors.append(f"第{index}天没有景点安排")
        if not day.meals:
            errors.append(f"第{index}天没有餐饮安排")

    if errors:
        raise TripPlanValidationError("；".join(errors))
    return plan
