"""Atomic, synchronous execution of structured plan changes."""
from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Protocol, Sequence, runtime_checkable

from ..models.schemas import Attraction, ChangeOperation, ChangeSet, Location, Meal, TripPlan, TripRequest
from .domain_errors import ChangeExecutionError
from .planning_context import DateUpdate, PlanningContext, POIRecord


@runtime_checkable
class AttractionResolver(Protocol):
    def resolve_attraction(self, target: Any, context: PlanningContext, operation: str = "") -> POIRecord | dict[str, Any] | None: ...


class ChangeResult:
    __slots__ = ("plan", "changes", "executed_operations", "updated_dates", "request")

    def __init__(self, plan: TripPlan, changes: Sequence[str] = (), executed_operations: Sequence[str] = (), updated_dates: DateUpdate | None = None, request: TripRequest | None = None):
        self.plan = plan.model_copy(deep=True)
        self.changes = tuple(str(item) for item in changes)
        self.executed_operations = tuple(str(item) for item in executed_operations)
        self.updated_dates = updated_dates
        self.request = request.model_copy(deep=True) if request is not None else None


class ChangeSetExecutor:
    """Apply a ChangeSet on copies; failure leaves caller-owned objects untouched."""

    _DAY_FIELDS = frozenset({"description", "transportation", "accommodation"})
    _KNOWN = frozenset({"delete_attraction", "replace_attraction", "replace_meal", "add_attraction", "update_day", "update_dates"})

    def __init__(self, resolver: AttractionResolver):
        self.resolver = resolver

    def execute(self, plan: TripPlan, request: TripRequest, context: PlanningContext, change_set: ChangeSet) -> ChangeResult:
        working = plan.model_copy(deep=True)
        request_copy = request.model_copy(deep=True)
        execution_context = replace(context, request=request_copy)
        changes: list[str] = []
        executed: list[str] = []
        updated_dates = None
        try:
            self._validate_operations(change_set.operations)
            for operation in change_set.operations:
                self._execute_one(working, request_copy, execution_context, operation, changes)
                executed.append(operation.operation)
                if operation.operation == "update_dates":
                    updated_dates = DateUpdate.from_fields(operation.fields)
            return ChangeResult(working, changes, executed, updated_dates, request_copy)
        except ChangeExecutionError:
            raise
        except Exception as exc:
            raise ChangeExecutionError(str(exc), cause=exc) from exc

    @classmethod
    def _validate_operations(cls, operations: Sequence[ChangeOperation]) -> None:
        if sum(op.operation == "update_dates" for op in operations) > 1:
            raise ChangeExecutionError("一次 ChangeSet 只能包含一个 update_dates", code="duplicate_update_dates")
        for op in operations:
            if op.operation == "full_replan":
                raise ChangeExecutionError("局部执行器不支持操作: full_replan", code="full_replan_not_supported")
            if op.operation not in cls._KNOWN:
                raise ChangeExecutionError(f"局部执行器不支持操作: {op.operation}", code="unknown_operation")

    def _execute_one(self, plan: TripPlan, request: TripRequest, context: PlanningContext, op: ChangeOperation, changes: list[str]) -> None:
        if op.operation == "update_dates":
            self._update_dates(plan, request, op, changes)
            return
        if op.operation == "delete_attraction":
            matches = self._matches(plan, op)
            if not matches:
                raise ChangeExecutionError("delete_attraction 没有匹配到任何景点", code="selector_not_found")
            for day, index, _ in reversed(matches):
                del day.attractions[index]
            changes.append("移除 " + "、".join(item.name for _, _, item in matches))
            return
        if op.operation == "replace_attraction":
            matches = self._matches(plan, op)
            if not matches:
                raise ChangeExecutionError("replace_attraction 没有匹配到待替换景点", code="selector_not_found")
            if len(matches) != 1:
                raise ChangeExecutionError("replace_attraction 选择器匹配多个景点", code="ambiguous_selector")
            poi = self._resolve(op, context)
            old = matches[0][2].name
            matches[0][0].attractions[matches[0][1]] = self._attraction(poi)
            changes.append(f"替换 {old} 为 {self._poi_name(poi)}")
            return
        if op.operation == "replace_meal":
            matches = self._meal_matches(plan, op)
            if not matches:
                raise ChangeExecutionError("replace_meal 没有匹配到待替换餐饮", code="selector_not_found")
            if len(matches) != 1:
                raise ChangeExecutionError("replace_meal 选择器匹配多个餐饮", code="ambiguous_selector")
            poi = self._resolve(op, context)
            day, index, old = matches[0]
            day.meals[index] = self._meal(poi, old.type)
            changes.append(f"替换{old.type} {old.name} 为 {self._poi_name(poi)}")
            return
        if op.operation == "add_attraction":
            index = op.selector.day_index if op.selector else None
            if index is None:
                index = min(range(len(plan.days)), key=lambda i: len(plan.days[i].attractions))
            if index < 0 or index >= len(plan.days):
                raise ChangeExecutionError("add_attraction 的 selector.day_index 超出行程范围", code="day_out_of_range")
            poi = self._resolve(op, context)
            plan.days[index].attractions.append(self._attraction(poi))
            changes.append(f"在第{index + 1}天添加 {self._poi_name(poi)}")
            return
        index = op.selector.day_index if op.selector else None
        if index is None or index < 0 or index >= len(plan.days):
            raise ChangeExecutionError("update_day 缺少有效的 selector.day_index", code="day_out_of_range")
        updated = [field for field, value in op.fields.items() if field in self._DAY_FIELDS and isinstance(value, str)]
        if not updated:
            raise ChangeExecutionError("update_day 没有可执行的白名单字段", code="no_allowed_fields")
        for field in updated:
            setattr(plan.days[index], field, op.fields[field])
        changes.append(f"更新第{index + 1}天: {', '.join(updated)}")

    @staticmethod
    def _matches(plan: TripPlan, op: ChangeOperation) -> list[tuple[Any, int, Attraction]]:
        selector = op.selector
        if selector is None:
            return []
        name = "".join((selector.name or "").split()).lower()
        semantic = "".join((selector.semantic or "").split()).lower()
        result = []
        for day in plan.days:
            if selector.day_index is not None and selector.day_index != day.day_index:
                continue
            for i, attraction in enumerate(day.attractions):
                text = "".join("|".join((attraction.name, attraction.description, attraction.category or "")).split()).lower()
                if (name or semantic) and (not name or name in text) and (not semantic or semantic in text):
                    result.append((day, i, attraction))
        return result

    @staticmethod
    def _meal_matches(plan: TripPlan, op: ChangeOperation) -> list[tuple[Any, int, Meal]]:
        selector = op.selector
        if selector is None:
            return []
        name = "".join((selector.name or "").split()).lower()
        semantic = "".join((selector.semantic or "").split()).lower()
        result = []
        for day in plan.days:
            if selector.day_index is not None and selector.day_index != day.day_index:
                continue
            for i, meal in enumerate(day.meals):
                text = "".join("|".join((meal.name, meal.description or "", meal.type or "")).split()).lower()
                if (name or semantic) and (not name or name in text) and (not semantic or semantic in text):
                    result.append((day, i, meal))
        return result

    def _resolve(self, op: ChangeOperation, context: PlanningContext) -> POIRecord | dict[str, Any]:
        target = op.target
        query = (getattr(target, "name", None) or getattr(target, "semantic", None) or "").strip() if target else ""
        if not query:
            raise ChangeExecutionError(f"{op.operation} 缺少 target.name 或 target.semantic", code="target_required")
        try:
            value = self.resolver.resolve_attraction(target, context, op.operation)
        except TypeError as exc:
            # 兼容旧版 resolver 的两参数接口。
            try:
                value = self.resolver.resolve_attraction(target, context)
            except TypeError:
                raise exc
        if value is None:
            raise ChangeExecutionError(f"在{context.city}范围内没有找到符合“{query}”的真实 POI", code="poi_not_found")
        return value

    @staticmethod
    def _poi_name(poi: Any) -> str:
        return poi.name if isinstance(poi, POIRecord) else str(poi.get("name") or "")

    @staticmethod
    def _location(data: dict[str, Any]) -> Location:
        raw = data.get("location")
        if isinstance(raw, Location):
            return raw
        if isinstance(raw, str) and "," in raw:
            longitude, latitude = (float(value) for value in raw.split(",", 1))
            return Location(longitude=longitude, latitude=latitude)
        if data.get("longitude") is not None and data.get("latitude") is not None:
            return Location(longitude=float(data["longitude"]), latitude=float(data["latitude"]))
        raise ChangeExecutionError("POI 缺少有效坐标", code="poi_location_required")

    @classmethod
    def _as_data(cls, poi: Any) -> dict[str, Any]:
        data = vars(poi) if isinstance(poi, POIRecord) else dict(poi)
        if isinstance(poi, POIRecord) and data.get("location") is None and data.get("longitude") is not None and data.get("latitude") is not None:
            data = {**data, "location": Location(longitude=data["longitude"], latitude=data["latitude"])}
        return data

    @classmethod
    def _attraction(cls, poi: Any) -> Attraction:
        data = cls._as_data(poi)
        return Attraction(name=str(data.get("name") or ""), address=str(data.get("address") or ""), location=cls._location(data), visit_duration=int(data.get("visit_duration", 120)), description=str(data.get("description") or data.get("type") or "真实高德 POI"), category=data.get("category", "景点"), rating=data.get("rating"), photos=list(data.get("photos") or []), image_url=data.get("image_url"), poi_id=str(data.get("poi_id") or data.get("id") or ""), ticket_price=int(data.get("ticket_price", data.get("cost") or 0) or 0))

    @classmethod
    def _meal(cls, poi: Any, meal_type: str) -> Meal:
        data = cls._as_data(poi)
        return Meal(type=meal_type, name=str(data.get("name") or ""), address=str(data.get("address") or ""), location=cls._location(data), description=str(data.get("description") or data.get("type") or "真实高德餐饮 POI"), estimated_cost=int(data.get("estimated_cost", data.get("ticket_price", data.get("cost") or 0)) or 0), poi_id=str(data.get("poi_id") or data.get("id") or ""))

    @staticmethod
    def _update_dates(plan: TripPlan, request: TripRequest, op: ChangeOperation, changes: list[str]) -> None:
        try:
            start, end = date.fromisoformat(op.fields["start_date"]), date.fromisoformat(op.fields["end_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ChangeExecutionError("update_dates 包含无效的起止日期", code="invalid_dates", cause=exc) from exc
        if start > end:
            raise ChangeExecutionError("update_dates 的开始日期不能晚于结束日期", code="invalid_dates")
        if (end - start).days + 1 != len(plan.days) or (end - start).days + 1 != request.travel_days:
            raise ChangeExecutionError("日期变更后的天数必须与当前行程天数一致", code="date_count_mismatch")
        plan.start_date, plan.end_date = start.isoformat(), end.isoformat()
        request.start_date, request.end_date = plan.start_date, plan.end_date
        for i, day in enumerate(plan.days):
            day.day_index, day.date = i, (start + timedelta(days=i)).isoformat()
        for i, weather in enumerate(plan.weather_info[:len(plan.days)]):
            weather.date = (start + timedelta(days=i)).isoformat()
        del plan.weather_info[len(plan.days):]
        changes.append(f"日期调整为 {plan.start_date} 至 {plan.end_date}")
