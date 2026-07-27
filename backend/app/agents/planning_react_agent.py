"""带最终校验闸门的旅行规划 ReAct Agent。"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional
from uuid import uuid4

from hello_agents import ReActAgent
from hello_agents.core.message import Message

from ..config import get_settings
from ..models.schemas import Location, TripPlan, TripRequest
from ..services.agent_loop_logging import _summary, log_agent_loop
from ..services.amap_photo_service import get_amap_photo_service
from ..services.trip_plan_validator import ValidationIssue, collect_trip_plan_issues


PLANNING_REACT_PROMPT = """你是行旅天下旅行规划 Agent。

可用工具：
{tools}

目标：根据当前任务生成完整 TripPlan。

输出规则：
1. 每轮只输出一条 Action，不输出 Thought、解释或 Markdown。
2. 格式必须是：Action: 工具名[JSON参数]
3. search_poi 的 purpose 只能是 attraction、meal 或 hotel。
4. 首次生成 Draft 前必须调用一次 purpose=meal 的 search_poi。
5. 每个大类先检索一次；只有该大类没有任何合格候选时，才调用一次 refresh=true。
   不要因为个别 POI 缺少价格字段就重复检索；优先从已有合格候选中选择。
   同一大类换关键词不会增加缓存信息，已检索过的大类请直接使用已有证据生成 Draft。
6. 所有景点、酒店和餐馆的名称、地址、坐标、POI ID、价格必须来自 search_poi。
7. 每餐必须有真实餐馆、地址、坐标、POI ID 和 estimated_cost，禁止占位餐馆。
8. 生成完整 Draft 后必须调用 validate_draft。
9. validate_draft 返回 passed=true 后，系统会立即交付已校验计划；无需再调用 Finish。
   若仍输出 Action: Finish[已通过校验]，系统也兼容处理。
10. Validator 失败时，只修复 issues 指出的内容；不要重复相同搜索。
11. 日期、天气和城市范围以当前任务及 Validator 为准，不调用额外天气工具。
12. 同一餐馆 POI 在整个行程中只能使用一次；相邻日程节点必须就近安排，禁止往返跨区。

当前任务：
{question}

执行历史：
{history}

示例：
Action: search_poi[{{"purpose":"meal","query":"目的地平价餐馆","category":"餐饮服务"}}]
"""


# 正常完整规划的 POI 类别是固定的；在模型调用前准备好这些候选，可以避免
# "餐饮 → 景点 → 酒店 → Draft" 四次串行模型调用。仍然只允许模型调用
# validate_draft，最终计划仍受同一份 POI 证据和 Validator 约束。
PRELOADED_EVIDENCE_REACT_PROMPT = """你是行旅天下旅行规划 Agent。

可用工具：
{tools}

目标：根据当前任务和已准备好的 POI 证据生成完整 TripPlan。

输出规则：
1. 每轮只输出一条 Action，不输出 Thought、解释或 Markdown。
2. 现在所有可用 POI 证据已在下方给出；不得搜索或虚构新的 POI。
3. 所有景点、酒店和餐馆的名称、地址、坐标、POI ID、价格必须逐字来自这些证据。
4. 每餐必须有真实餐馆、地址、坐标、POI ID 和 estimated_cost。
5. 立刻生成完整 Draft，并输出：Action: validate_draft[完整 TripPlan JSON]。
6. Validator 失败时，只修复 issues 指出的内容后再次调用 validate_draft。
7. 日期、天气和城市范围以当前任务及 Validator 为准，不调用额外天气工具。
8. 每天只安排相互邻近的一片区域；景点按就近顺序安排，避免从城区东侧跳到西侧后又折返。
9. 同一餐馆 POI 在整个行程中只能使用一次；将早餐、景点、午餐、晚餐安排在相近片区，禁止远距离往返。
10. 为确保快速交付，description 使用简短短语（不超过 12 个汉字），overall_suggestions 不超过 50 个汉字；不要输出任何解释文字。

当前任务：
{question}

执行历史：
{history}
"""


def _normalise_request_facts(payload: dict, request: TripRequest) -> dict:
    """统一模型 Draft 的展示格式，并由后端写入不可变的时间线字段。"""

    def normalise_location(value: object) -> object:
        """接受高德常用的 ``经度,纬度`` 字符串，输出 Schema 所需对象。"""
        if not isinstance(value, str):
            return value
        try:
            longitude, latitude = (float(item.strip()) for item in value.split(",", 1))
        except (TypeError, ValueError):
            return value
        return {"longitude": longitude, "latitude": latitude}

    def normalise_cost(value: object) -> object:
        if isinstance(value, str):
            match = re.search(r"\d+(?:\.\d+)?", value)
            return int(float(match.group())) if match else value
        return value

    def normalise_duration(value: object) -> object:
        if not isinstance(value, str):
            return value
        hours = re.search(r"(\d+(?:\.\d+)?)\s*小时", value)
        minutes = re.search(r"(\d+)\s*分钟", value)
        if hours:
            return int(float(hours.group(1)) * 60)
        if minutes:
            return int(minutes.group(1))
        return value

    meal_types = {"早餐": "breakfast", "早饭": "breakfast", "午餐": "lunch", "中餐": "lunch", "晚餐": "dinner", "晚饭": "dinner", "小吃": "snack"}

    def normalise_poi(item: object, *, duration: bool = False) -> object:
        if not isinstance(item, Mapping):
            return item
        result = dict(item)
        result["location"] = normalise_location(result.get("location"))
        if "estimated_cost" in result:
            result["estimated_cost"] = normalise_cost(result["estimated_cost"])
        if duration and "visit_duration" in result:
            result["visit_duration"] = normalise_duration(result["visit_duration"])
        return result

    def normalise_day(day: object, index: int, start: date) -> object:
        if not isinstance(day, Mapping):
            return day
        result = dict(day)
        hotel = result.get("hotel")
        accommodation = result.get("accommodation")
        # 模型常把完整酒店 POI 写进 accommodation；迁移到明确的 hotel 字段。
        if isinstance(accommodation, Mapping):
            hotel = hotel if isinstance(hotel, Mapping) else accommodation
            result["accommodation"] = str(
                accommodation.get("type") or request.accommodation or accommodation.get("name") or ""
            )
        if isinstance(hotel, Mapping):
            result["hotel"] = normalise_poi(hotel)

        result["date"] = (start + timedelta(days=index)).isoformat()
        result["day_index"] = index
        result["transportation"] = result.get("transportation") or request.transportation
        result["accommodation"] = result.get("accommodation") or request.accommodation
        result["attractions"] = [
            normalise_poi(item, duration=True) for item in result.get("attractions", [])
        ]
        meals = []
        for meal in result.get("meals", []):
            normalised_meal = normalise_poi(meal)
            if isinstance(normalised_meal, dict):
                normalised_meal["type"] = meal_types.get(
                    str(normalised_meal.get("type") or "").strip(),
                    normalised_meal.get("type"),
                )
            meals.append(normalised_meal)
        result["meals"] = meals
        return result

    plan = dict(payload)
    plan.update({
        "city": request.city,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "weather_info": [],
    })
    start = date.fromisoformat(request.start_date)
    days = plan.get("days")
    if isinstance(days, list):
        plan["days"] = [normalise_day(day, index, start) for index, day in enumerate(days)]
    return plan


class PlanningLoopError(RuntimeError):
    """ReAct 规划在未通过校验时终止。"""


@dataclass
class PlanningSession:
    request: TripRequest
    city_center: Optional[Location]
    radius_km: float
    target_adcode: Optional[str]
    amap_city: str
    cached_pois: list[dict] = field(default_factory=list)
    validated_plan: Optional[TripPlan] = None
    evidence_ids: dict[str, set[str]] = field(default_factory=dict)
    evidence_records: dict[str, dict[str, dict]] = field(default_factory=dict)
    search_history: set[str] = field(default_factory=set)
    searched_purposes: set[str] = field(default_factory=set)
    refresh_count: dict[str, int] = field(default_factory=dict)
    invalid_response_count: int = 0
    validation_attempts: int = 0
    evidence_preloaded: bool = False
    preloaded_evidence: str = ""


class PlanningToolset:
    """向 ReAct 暴露少量领域工具，隐藏底层高德接口细节。"""

    def __init__(self, session: PlanningSession):
        self.session = session

    @staticmethod
    def _input_json(input_text: str) -> dict:
        text = (input_text or "").strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {"query": text}
        except json.JSONDecodeError:
            return {"query": text}

    def _cached_candidates(self, purpose: str) -> list[dict]:
        """把 Chroma 元数据转换成与高德搜索一致的证据格式。"""
        threshold = get_settings().poi_vector_distance_threshold
        candidates = []
        for poi in self.session.cached_pois:
            if poi.get("poi_group") != purpose:
                continue
            distance = poi.get("distance")
            if distance is not None and float(distance) > threshold:
                continue
            longitude = poi.get("longitude")
            latitude = poi.get("latitude")
            if longitude is None or latitude is None:
                continue
            candidates.append({
                "poi_id": poi.get("poi_id") or "",
                "name": poi.get("name") or "",
                "address": poi.get("address") or "",
                "location": f"{longitude},{latitude}",
                "type": poi.get("type") or "",
                "typecode": poi.get("typecode") or "",
                "rating": poi.get("rating") or "",
                "cost": poi.get("cost") or "",
                "distance": distance,
                "source": "chroma",
            })
        candidates.sort(
            key=lambda item: (
                float(item["distance"]) if item.get("distance") is not None else 999.0,
                item.get("name") or "",
            )
        )
        return candidates[: get_settings().poi_vector_top_k]

    def _record_evidence(self, purpose: str, candidates: list[dict]) -> None:
        self.session.evidence_ids.setdefault(purpose, set()).update(
            str(item["poi_id"]) for item in candidates if item["poi_id"]
        )
        self.session.evidence_records.setdefault(purpose, {}).update({
            str(item["poi_id"]): item for item in candidates if item["poi_id"]
        })

    @staticmethod
    def _compact_candidate(candidate: dict, purpose: str) -> dict:
        """保留生成和证据核验必需字段，避免 Observation 撑大下一次 Prompt。"""
        compact = {
            key: candidate.get(key, "")
            for key in ("poi_id", "name", "address", "location", "type")
        }
        if purpose == "meal":
            compact["cost"] = candidate.get("cost", "")
        return compact

    def prepare_required_evidence(self) -> bool:
        """预取完整规划必需的三类证据，令正常路径只需一次模型调用。

        复用 ``search_poi``，因此 Chroma/高德兜底、行政区过滤和 evidence
        记录逻辑完全一致。任一类没有候选时回退到原 ReAct 模式，让模型可按需
        触发 refresh，而不是把空证据误标成已准备完成。
        """
        request = self.session.request
        searches = (
            ("meal", f"{request.city} 平价餐馆", "餐饮服务"),
            ("attraction", f"{request.city} 景点", "风景名胜"),
            ("hotel", f"{request.city} 经济型酒店", "住宿服务"),
        )
        evidence: dict[str, list[dict]] = {}
        for purpose, query, category in searches:
            result = json.loads(self.search_poi(json.dumps({
                "purpose": purpose,
                "query": query,
                "category": category,
            }, ensure_ascii=False)))
            candidates = result.get("candidates", [])
            required_meal_count = self.session.request.travel_days * len(
                [item for item in get_settings().required_meal_types.split(",") if item.strip()]
            )
            if purpose == "meal" and len(candidates) < required_meal_count:
                # 向量缓存只命中少量餐厅时，主动触发一次高德补查；否则模型即使
                # 遵守“不得重复”也没有足够的真实 POI 可选。
                result = json.loads(self.search_poi(json.dumps({
                    "purpose": purpose,
                    "query": query,
                    "category": category,
                    "refresh": True,
                }, ensure_ascii=False)))
                candidates = list(self.session.evidence_records.get(purpose, {}).values())
            if not isinstance(candidates, list) or not candidates:
                self.session.evidence_preloaded = False
                self.session.preloaded_evidence = ""
                return False
            settings = get_settings()
            # 三天计划需 9 餐。原先固定展示 4 个餐饮候选，等同诱导模型
            # 重复同一美食城；餐饮至少展示每个必需餐次一个不同候选。
            limit = (
                max(
                    settings.planner_preloaded_candidate_limit,
                    self.session.request.travel_days * len(
                        [item for item in settings.required_meal_types.split(",") if item.strip()]
                    ),
                )
                if purpose == "meal"
                else settings.planner_preloaded_candidate_limit
            )
            evidence[purpose] = [
                self._compact_candidate(candidate, purpose)
                for candidate in candidates[:limit]
                if isinstance(candidate, dict) and candidate.get("poi_id")
            ]
            if not evidence[purpose] or (
                purpose == "meal" and len(evidence[purpose]) < required_meal_count
            ):
                self.session.evidence_preloaded = False
                self.session.preloaded_evidence = ""
                return False

        self.session.evidence_preloaded = True
        self.session.preloaded_evidence = json.dumps(
            {"poi_evidence": evidence}, ensure_ascii=False, separators=(",", ":")
        )
        return True

    def search_poi(self, input_text: str) -> str:
        """先查对应大类的 Chroma 候选，不足时由 Agent 显式 refresh 调高德。"""
        payload = self._input_json(input_text)
        query = str(payload.get("query") or "").strip()
        purpose = str(payload.get("purpose") or "").strip()
        category = str(payload.get("category") or "").strip()
        refresh = bool(payload.get("refresh"))
        if not query:
            return json.dumps({"error": "query 不能为空"}, ensure_ascii=False)
        if purpose not in {"attraction", "meal", "hotel"}:
            return json.dumps({
                "error": "purpose 必须是 attraction、meal 或 hotel",
            }, ensure_ascii=False)

        signature = json.dumps(
            {
                "purpose": purpose,
                "query": query,
                "category": category,
                "refresh": refresh,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if signature in self.session.search_history:
            existing = list(self.session.evidence_records.get(purpose, {}).values())
            return json.dumps({
                "query": query,
                "purpose": purpose,
                "category": category,
                "source": "reused_evidence",
                "candidates": existing,
                "instruction": "该搜索已执行过，请直接使用已有候选或调用其他大类工具。",
            }, ensure_ascii=False)
        self.session.search_history.add(signature)

        # 当前缓存检索按大类召回，query 只用于展示和后续高德兜底，
        # 因此同一 purpose 的重复关键词不会带来新证据。允许显式
        # refresh 重新查一次，其他重复查询直接复用已记录的 POI。
        if not refresh and purpose in self.session.searched_purposes:
            existing = list(self.session.evidence_records.get(purpose, {}).values())
            return json.dumps({
                "query": query,
                "purpose": purpose,
                "category": category,
                "source": "reused_evidence",
                "candidates": existing,
                "instruction": "该大类已检索过；不要继续更换关键词，请直接生成或校验 Draft。",
            }, ensure_ascii=False)

        if refresh:
            refresh_limit = get_settings().planner_max_refresh_per_purpose
            used_refreshes = self.session.refresh_count.get(purpose, 0)
            if used_refreshes >= refresh_limit:
                existing = list(self.session.evidence_records.get(purpose, {}).values())
                return json.dumps({
                    "query": query,
                    "purpose": purpose,
                    "category": category,
                    "source": "refresh_limit_reached",
                    "candidates": existing,
                    "instruction": "该大类已达到 refresh 上限，请使用已有候选生成或校验 Draft。",
                }, ensure_ascii=False)
            self.session.refresh_count[purpose] = used_refreshes + 1

        if not refresh:
            cached_candidates = self._cached_candidates(purpose)
            if cached_candidates:
                self._record_evidence(purpose, cached_candidates)
                self.session.searched_purposes.add(purpose)
                return json.dumps({
                    "query": query,
                    "purpose": purpose,
                    "category": category,
                    "source": "chroma",
                    "candidates": cached_candidates,
                    "distance_threshold": get_settings().poi_vector_distance_threshold,
                    "instruction": (
                        "请从候选中选择；只有没有任何合格候选时，"
                        "才对该大类使用一次 refresh=true"
                    ),
                }, ensure_ascii=False)

        keywords = " ".join(item for item in (self.session.request.city, query, category) if item)
        raw_pois = get_amap_photo_service().search_pois(
            keywords,
            city=self.session.amap_city,
            offset=get_settings().planner_candidate_limit,
        )
        candidates = []
        for poi in raw_pois:
            adcode = str(poi.get("adcode") or "").strip()
            if self.session.target_adcode and adcode and adcode != self.session.target_adcode:
                continue
            biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
            candidates.append({
                "poi_id": poi.get("id") or "",
                "name": poi.get("name") or "",
                "address": poi.get("address") or "",
                "location": poi.get("location") or "",
                "type": poi.get("type") or "",
                "typecode": poi.get("typecode") or "",
                "rating": biz_ext.get("rating") or "",
                "cost": biz_ext.get("cost") or "",
            })
        self._record_evidence(purpose, candidates)
        self.session.searched_purposes.add(purpose)
        return json.dumps({
            "query": query,
            "purpose": purpose,
            "category": category,
            "source": "amap",
            "candidates": candidates,
            "distance_threshold": get_settings().poi_vector_distance_threshold,
            "fallback_reason": (
                "refresh=true，强制高德搜索"
                if refresh
                else "Chroma 没有达到相关性阈值的候选"
            ),
            "instruction": "候选已返回；请直接生成 Draft 并调用 validate_draft。只有没有任何合格候选时才 refresh。",
        }, ensure_ascii=False)

    def validate_draft(self, input_text: str) -> str:
        """校验完整 Draft，并保存最近一次通过校验的版本。"""
        self.session.validation_attempts += 1
        try:
            payload = json.loads((input_text or "").strip())
            if not isinstance(payload, dict):
                raise TypeError("TripPlan Draft 必须是 JSON 对象")
            plan = TripPlan.model_validate(
                _normalise_request_facts(payload, self.session.request)
            )
        except Exception as error:
            self.session.validated_plan = None
            return json.dumps({
                "passed": False,
                "issues": [{"code": "DRAFT_SCHEMA_INVALID", "message": str(error)}],
            }, ensure_ascii=False)

        issues = collect_trip_plan_issues(
            plan,
            self.session.request,
            self.session.city_center,
            self.session.radius_km,
        )
        meal_evidence = self.session.evidence_ids.get("meal", set())
        meal_records = self.session.evidence_records.get("meal", {})
        for day_index, day in enumerate(plan.days):
            for meal in day.meals:
                if meal.poi_id and meal.poi_id not in meal_evidence:
                    issues.append(ValidationIssue(
                        code="MEAL_POI_UNVERIFIED",
                        message=f"餐饮“{meal.name}”的 POI ID 不在本轮餐馆搜索证据中",
                        day_index=day_index,
                        entity_type="meal",
                        entity_name=meal.name,
                    ))
                    continue
                candidate = meal_records.get(meal.poi_id)
                if candidate and not self._matches_meal_evidence(meal, candidate):
                    issues.append(ValidationIssue(
                        code="MEAL_POI_FACT_MISMATCH",
                        message=f"餐饮“{meal.name}”的名称、地址或坐标与本轮高德 POI 证据不一致",
                        day_index=day_index,
                        entity_type="meal",
                        entity_name=meal.name,
                    ))
        self.session.validated_plan = plan if not issues else None
        return json.dumps({
            "passed": not issues,
            "issues": [issue.model_dump() for issue in issues],
        }, ensure_ascii=False)

    @staticmethod
    def _matches_meal_evidence(meal, candidate: dict) -> bool:
        """确认交付餐饮节点直接来自本轮高德候选，禁止仅借用 POI ID。"""
        def normalise(value: object) -> str:
            return "".join(str(value or "").split())

        if normalise(meal.name) != normalise(candidate.get("name")):
            return False
        if normalise(meal.address) != normalise(candidate.get("address")):
            return False
        try:
            longitude, latitude = (float(item) for item in str(candidate["location"]).split(",", 1))
        except (KeyError, TypeError, ValueError):
            return False
        return bool(
            meal.location
            and abs(meal.location.longitude - longitude) < 0.000001
            and abs(meal.location.latitude - latitude) < 0.000001
        )


class ValidatedPlanningReActAgent(ReActAgent):
    """仅允许在最新 Draft 通过 Validator 后 Finish。"""

    def __init__(self, *, llm, session: PlanningSession):
        settings = get_settings()
        super().__init__(
            name="旅行规划 ReAct Agent",
            llm=llm,
            max_steps=settings.planner_max_react_steps,
            custom_prompt=(
                PRELOADED_EVIDENCE_REACT_PROMPT
                if session.evidence_preloaded
                else PLANNING_REACT_PROMPT
            ),
        )
        self.session = session
        self.max_stalled_steps = settings.planner_max_stalled_steps
        domain_tools = PlanningToolset(session)
        if not session.evidence_preloaded:
            self.tool_registry.register_function(
                "search_poi",
                "先搜索对应大类的 Chroma 候选；结果不足时设置 refresh=true 调高德。输入单行 JSON: purpose, query, category, refresh(可选)",
                domain_tools.search_poi,
            )
        self.tool_registry.register_function(
            "validate_draft",
            "校验完整 TripPlan Draft；输入单行 TripPlan JSON",
            domain_tools.validate_draft,
        )

    def run(self, input_text: str, **kwargs) -> str:
        self.current_history = (
            [f"已准备好的 POI 证据：{self.session.preloaded_evidence}"]
            if self.session.evidence_preloaded
            else []
        )
        run_id = uuid4().hex
        started = time.perf_counter()
        previous_signature = ""
        stalled_steps = 0
        log_agent_loop("run_start", run_id, agent_type="react", max_steps=self.max_steps)

        for step in range(1, self.max_steps + 1):
            prompt = self.prompt_template.format(
                tools=self.tool_registry.get_tools_description(),
                question=input_text,
                history="\n".join(self.current_history),
            )
            model_started = time.perf_counter()
            try:
                response_text = self.llm.invoke(
                    [{"role": "user", "content": prompt}], **kwargs
                ) or ""
            except Exception as error:
                log_agent_loop(
                    "run_error",
                    run_id,
                    agent_type="react",
                    iteration=step,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    model_duration_ms=round((time.perf_counter() - model_started) * 1000),
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
                raise
            thought, action = self._parse_output(response_text)
            if not action:
                self.session.invalid_response_count += 1
                observation = (
                    "输出格式无效：必须只输出一条 Action。"
                    "格式为 Action: 工具名[JSON参数]；"
                    "如果已经准备好完整计划，直接调用 validate_draft[完整 TripPlan JSON]。"
                )
                self.current_history.extend([
                    f"Invalid response: {_summary(response_text)}",
                    f"Observation: {observation}",
                ])
                log_agent_loop(
                    "react_observation",
                    run_id,
                    iteration=step,
                    observation_summary=observation,
                    invalid_response_summary=response_text,
                    prompt_full=prompt,
                    model_response_full=response_text,
                    observation_full=observation,
                )
                if self.session.invalid_response_count > get_settings().planner_max_invalid_responses:
                    log_agent_loop(
                        "run_end",
                        run_id,
                        agent_type="react",
                        iteration=step,
                        termination_reason="invalid_response_limit",
                        duration_ms=round((time.perf_counter() - started) * 1000),
                    )
                    raise PlanningLoopError("ReAct 连续输出无效格式，已停止重试")
                continue
            tool_name, tool_input = (
                ("Finish", None)
                if action.startswith("Finish")
                else self._parse_action(action)
            )
            log_agent_loop(
                "react_step",
                run_id,
                iteration=step,
                agent_type="react",
                duration_ms=round((time.perf_counter() - model_started) * 1000),
                prompt_full=prompt,
                model_response_full=response_text,
                thought_summary=_summary(thought or ""),
                action_summary=_summary(action),
                action_details=action,
                tool_name=tool_name,
                tool_input_details=tool_input,
            )

            tool_duration_ms = None
            if action.startswith("Finish"):
                if self.session.validated_plan is not None:
                    result = self.session.validated_plan.model_dump_json()
                    self.add_message(Message(input_text, "user"))
                    self.add_message(Message(result, "assistant"))
                    log_agent_loop(
                        "run_end",
                        run_id,
                        agent_type="react",
                        termination_reason="validator_passed",
                        duration_ms=round((time.perf_counter() - started) * 1000),
                        delivered_plan=self.session.validated_plan.model_dump(),
                    )
                    return result
                observation = json.dumps({
                    "passed": False,
                    "issues": [{
                        "code": "PREMATURE_FINISH",
                        "message": "当前 Draft 尚未通过 validate_draft，禁止交付",
                    }],
                }, ensure_ascii=False)
            else:
                if not tool_name or tool_input is None:
                    observation = "无效 Action 格式；请使用 工具名[参数]"
                else:
                    try:
                        tool_started = time.perf_counter()
                        observation = self.tool_registry.execute_tool(tool_name, tool_input)
                        tool_duration_ms = round((time.perf_counter() - tool_started) * 1000)
                    except Exception as error:
                        log_agent_loop(
                            "run_error",
                            run_id,
                            agent_type="react",
                            iteration=step,
                            duration_ms=round((time.perf_counter() - started) * 1000),
                            tool_name=tool_name,
                            error_type=type(error).__name__,
                            error_message=str(error),
                        )
                        raise

            self.current_history.extend([
                f"Thought: {thought or ''}",
                f"Action: {action}",
                f"Observation: {observation}",
            ])
            log_agent_loop(
                "react_observation",
                run_id,
                iteration=step,
                tool_name=tool_name,
                tool_duration_ms=tool_duration_ms if tool_name else None,
                observation_full=observation,
                observation_summary=observation,
            )
            # Validator 已通过就是可靠的终止条件。再让模型额外输出一轮
            # Finish 没有信息增益，反而可能在 max_steps 边界把成功计划误报为失败。
            if tool_name == "validate_draft" and self.session.validated_plan is not None:
                result = self.session.validated_plan.model_dump_json()
                self.add_message(Message(input_text, "user"))
                self.add_message(Message(result, "assistant"))
                log_agent_loop(
                    "run_end",
                    run_id,
                    agent_type="react",
                    iteration=step,
                    termination_reason="validator_passed",
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    delivered_plan=self.session.validated_plan.model_dump(),
                )
                return result
            signature = f"{action}\n{observation}"
            stalled_steps = stalled_steps + 1 if signature == previous_signature else 0
            previous_signature = signature
            if stalled_steps >= self.max_stalled_steps:
                log_agent_loop(
                    "run_end",
                    run_id,
                    agent_type="react",
                    termination_reason="no_progress",
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
                raise PlanningLoopError("ReAct 连续重复相同行动且结果无变化")

        log_agent_loop(
            "run_end",
            run_id,
            agent_type="react",
            termination_reason="max_steps_reached",
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        raise PlanningLoopError("ReAct 达到最大步数，Draft 仍未通过 Validator")

    @staticmethod
    def _parse_output(text: str):
        # 兼容普通文本、Markdown 加粗以及全角冒号，避免模型已经给出
        # Action 但因格式是 ``**Action:**`` 或 ``Action：`` 被误判为无效。
        thought_match = re.search(
            r"(?is)(?:^|\n)\s*(?:\*\*)?Thought(?:\*\*)?\s*[:：]\s*"
            r"(.*?)(?=\n\s*(?:\*\*)?Action(?:\*\*)?\s*[:：])",
            text,
        )
        action_match = re.search(
            r"(?im)(?:^|\n)\s*(?:[*#`]+\s*)?Action\s*[:：]\s*(?:\*+)?\s*"
            r"([A-Za-z_]\w*)\s*\[",
            text,
        )
        action = None
        if action_match:
            # Draft 很容易被模型排版为多行 JSON。按方括号层级提取完整 Action，
            # 并跳过 JSON 字符串里的方括号，避免将合法提交误判为格式错误。
            start = action_match.start(1)
            bracket_start = text.find("[", start)
            depth = 0
            in_string = False
            escaped = False
            for index in range(bracket_start, len(text)):
                char = text[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                    if depth == 0:
                        action = text[start:index + 1].strip()
                        break
        if action is None:
            # 某些模型会先说明选择理由，再直接输出完整 TripPlan JSON，遗漏
            # Action 标签。只要其中含完整 days 字段，就把它安全地送入同一个
            # Validator；普通搜索结果没有 days，不会被误当成交付计划。
            decoder = json.JSONDecoder()
            for index, char in enumerate(text or ""):
                if char != "{":
                    continue
                try:
                    payload, _ = decoder.raw_decode(text[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict) and isinstance(payload.get("days"), list):
                    action = "validate_draft[" + json.dumps(
                        payload, ensure_ascii=False, separators=(",", ":")
                    ) + "]"
                    break
        return (
            thought_match.group(1).strip() if thought_match else None,
            action,
        )

    @staticmethod
    def _parse_action(action_text: str):
        match = re.fullmatch(r"([A-Za-z_]\w*)\[(.*)\]", action_text.strip(), re.DOTALL)
        return (match.group(1), match.group(2)) if match else (None, None)
