"""CP0 特征测试：锁定 TripPlanningService.plan_trip() 的 6 条关键行为。

这些测试描述的是**现状行为**（characterization），不是理想行为：
它们是后续重构（文件合并、状态机、Tool 类化、logging）的安全网。
任何一条测试失败，说明重构改变了对外可见的编排语义，必须停下对账。

只伪造基础设施接缝（高德 HTTP、Chroma、LLM、图片服务），
编排控制流全部走真实代码。

对应关系（行号以 2026-09-18 工作区为准）：
    T1 定向修改成功直接返回，不触发全量规划        trip_planning_service.py:216-235
    T2 定向修改失败抛 TargetedReplanUnsatisfiable，
       不降级全量重排                              :236-248（刻意设计）
    T3 确定性排程 ROUTE_LEG_TOO_LONG → refresh
       补证据重排 → 仍失败转 ReAct                 :283-329
    T4 Chroma 召回超时 → 主线程继续，
       后台向量查询放行热身                        :179-205
    T5 定向修改/预加载证据模式跳过图片补齐          :372-391
    T6 ReAct 结束但无 Validator 通过的计划 →
       RuntimeError，禁止占位数据伪装               :337-338
"""

import json
import time
from datetime import date, timedelta

import pytest

import app.services.trip_planning_service as tps
from app.config import get_settings
from app.models.schemas import ChangeOperation, ChangeSet, Location, TripPlan, TripRequest
from app.services.change_set_executor import ChangeExecutionError, TargetedReplanUnsatisfiable
from app.services.planning_service import PlanningToolset
from app.services.trip_plan_validator import TripPlanValidationError


# ---------------------------------------------------------------------------
# 伪造的基础设施
# ---------------------------------------------------------------------------

class FakeLLM:
    """这些测试不经过真实模型；任何 LLM 调用都说明路径走错。"""

    def invoke(self, *args, **kwargs):
        raise AssertionError("测试路径不应调用 LLM")


class FakeAmap:
    """高德服务替身：行政区解析与天气全部本地返回。"""

    def __init__(self, adcode="110100", center=(116.40, 39.90), search_city="北京"):
        self.adcode = adcode
        self.center = center
        self.search_city = search_city
        self.weather_calls = []

    def get_city_center(self, city):
        return Location(longitude=self.center[0], latitude=self.center[1])

    def get_city_adcode(self, city):
        return self.adcode

    def get_poi_search_city(self, city):
        return self.search_city

    def get_weather(self, city):
        self.weather_calls.append(city)
        return []


class ForbiddenReActAgent:
    """哨兵：任何全量 ReAct 规划都视为测试路径走错。"""

    def __init__(self, **kwargs):
        raise AssertionError("不应触发 ReAct 全量规划")

    def run(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("不应触发 ReAct 全量规划")


# ---------------------------------------------------------------------------
# 构造最小合法数据
# ---------------------------------------------------------------------------

START_DATE = "2026-10-01"


def make_plan_dict(city="北京", days=1, attraction_name=None):
    """构造可通过 TripPlan.model_validate 的最小计划。"""
    start = date.fromisoformat(START_DATE)
    day_entries = []
    for index in range(days):
        day = {
            "date": (start + timedelta(days=index)).isoformat(),
            "day_index": index,
            "description": f"第{index + 1}天行程",
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
            "attractions": [
                {
                    "name": attraction_name or f"测试景点{index}",
                    "address": "测试路1号",
                    "location": {"longitude": 116.40, "latitude": 39.90},
                    "visit_duration": 120,
                    "description": "特征测试用景点",
                }
            ],
            "meals": [],
        }
        day_entries.append(day)
    return {
        "city": city,
        "start_date": START_DATE,
        "end_date": (start + timedelta(days=days - 1)).isoformat(),
        "overall_suggestions": "特征测试计划",
        "days": day_entries,
    }


def make_plan(**kwargs):
    return TripPlan.model_validate(make_plan_dict(**kwargs))


def make_request(city="北京", **overrides):
    payload = {
        "city": city,
        "start_date": START_DATE,
        "end_date": "2026-10-01",
        "travel_days": 1,
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
        "preferences": [],
    }
    payload.update(overrides)
    return TripRequest(**payload)


# ---------------------------------------------------------------------------
# 公共夹具
# ---------------------------------------------------------------------------

@pytest.fixture
def service(monkeypatch):
    """构造 TripPlanningService，基础设施接缝全部替换。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "planner_preload_poi_evidence", True)
    monkeypatch.setattr(settings, "planner_preloaded_deterministic_plan", True)

    monkeypatch.setattr(tps, "get_llm", lambda: FakeLLM())
    fake_amap = FakeAmap()
    import app.services.amap_service as amap_module
    monkeypatch.setattr(amap_module, "get_amap_service", lambda: fake_amap)

    # 天气补查是纯网络 IO，与编排无关，固定替换。
    monkeypatch.setattr(
        tps.TripPlanningService,
        "_complete_weather_for_travel_dates",
        staticmethod(lambda weather_info, request, city_center=None: []),
    )
    return tps.TripPlanningService()


@pytest.fixture
def image_recorders(monkeypatch):
    """记录图片补齐两条路径的调用；返回 (meal_calls, image_calls)。"""
    meal_calls = []
    image_calls = []

    def fake_meal(plan, **kwargs):
        meal_calls.append(plan)
        return plan

    def fake_image(plan, **kwargs):
        image_calls.append(plan)
        return plan

    monkeypatch.setattr(
        tps.TripPlanningService, "_enrich_meal_pois", staticmethod(fake_meal)
    )
    monkeypatch.setattr(
        tps.TripPlanningService, "_enrich_attraction_images", staticmethod(fake_image)
    )
    return meal_calls, image_calls


@pytest.fixture
def final_validate_recorder(monkeypatch):
    """最终 validate_trip_plan 闸门替换为记录器（真实校验需要完整富化计划）。"""
    calls = []

    def recorder(plan, request, **kwargs):
        calls.append({"plan": plan, "kwargs": kwargs})
        return None

    monkeypatch.setattr(tps, "validate_trip_plan", recorder)
    return calls


def install_passing_toolset(monkeypatch, service, draft):
    """确定性路径一次通过：证据预取 True + 排程产出 draft + validate_draft 通过。"""

    def fake_prepare(self):
        return True

    def fake_validate(self, input_text):
        # 与真实 validate_draft 的状态机写入一致：通过 → validated
        self.session.plan = draft
        draft.status = "validated"
        return json.dumps({"passed": True, "issues": []}, ensure_ascii=False)

    monkeypatch.setattr(PlanningToolset, "prepare_required_evidence", fake_prepare)
    monkeypatch.setattr(PlanningToolset, "validate_draft", fake_validate)
    monkeypatch.setattr(service, "_build_evidence_plan", lambda request, session: draft)


def install_react_agent(monkeypatch, react_plan, deliver=True):
    """替换 ValidatedPlanningReActAgent。

    deliver=True：模拟 Validator 已通过（plan.status="validated"）后交付；
    deliver="draft"：模拟返回了计划实例但状态仍是 draft（未过 Validator）；
    deliver=False：模拟没有任何计划实例。
    """
    instances = []

    class FakeReActAgent:
        def __init__(self, *, llm, session):
            self.llm = llm
            self.session = session
            instances.append(self)

        def run(self, input_text, **kwargs):
            if deliver is True:
                self.session.plan = react_plan
                react_plan.status = "validated"
            elif deliver == "draft":
                self.session.plan = react_plan  # status 保持默认 draft
            return react_plan.model_dump_json()

    monkeypatch.setattr(tps, "ValidatedPlanningReActAgent", FakeReActAgent)
    return instances


# ---------------------------------------------------------------------------
# T1 定向修改成功：直接返回，不触发全量规划
# ---------------------------------------------------------------------------

def test_t1_targeted_change_success_returns_directly(
    service, monkeypatch, image_recorders, final_validate_recorder
):
    request = make_request(
        current_plan=make_plan_dict(),
        change_set=ChangeSet(operations=[
            ChangeOperation(operation="replace_meal", selector={"name": "午餐"})
        ]),
    )

    modified = make_plan(attraction_name="修改后景点")
    change_calls = []

    def fake_execute(plan, change_set, req, vector_pois, target_adcode):
        change_calls.append(change_set)
        return modified, ["已替换餐厅"]

    monkeypatch.setattr(service, "_execute_change_set", fake_execute)

    def forbidden_build(*args, **kwargs):
        raise AssertionError("定向修改成功后不应触发确定性全量排程")

    monkeypatch.setattr(service, "_build_evidence_plan", forbidden_build)
    monkeypatch.setattr(tps, "ValidatedPlanningReActAgent", ForbiddenReActAgent)

    result = service.plan_trip(request)

    assert result is modified
    assert change_calls == [request.change_set]
    # 定向修改分支内的校验闸门必须跑过（:226）
    assert len(final_validate_recorder) == 1
    assert final_validate_recorder[0]["kwargs"]["require_enriched_locations"] is True


# ---------------------------------------------------------------------------
# T2 定向修改失败：如实上报 TargetedReplanUnsatisfiable，不降级全量重排
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "failure",
    [
        {"kind": "execution", "error": ChangeExecutionError("范围内找不到真实 POI")},
        {"kind": "validation", "error": TripPlanValidationError("替换餐饮超出步行范围")},
    ],
    ids=["executor-fails", "validation-fails"],
)
def test_t2_targeted_change_failure_raises_no_fallback(
    service, monkeypatch, failure, image_recorders, final_validate_recorder
):
    request = make_request(
        current_plan=make_plan_dict(),
        change_set=ChangeSet(operations=[
            ChangeOperation(operation="replace_meal", selector={"name": "午餐"})
        ]),
    )

    if failure["kind"] == "execution":
        def fake_execute(plan, change_set, req, vector_pois, target_adcode):
            raise failure["error"]
        monkeypatch.setattr(service, "_execute_change_set", fake_execute)
    else:
        def failing_validate(plan, request, **kwargs):
            raise failure["error"]
        monkeypatch.setattr(tps, "validate_trip_plan", failing_validate)

    def forbidden_build(*args, **kwargs):
        raise AssertionError("定向修改失败必须如实上报，不允许降级为全量重排")

    monkeypatch.setattr(service, "_build_evidence_plan", forbidden_build)
    monkeypatch.setattr(tps, "ValidatedPlanningReActAgent", ForbiddenReActAgent)

    with pytest.raises(TargetedReplanUnsatisfiable):
        service.plan_trip(request)


# ---------------------------------------------------------------------------
# T3 确定性排程 ROUTE_LEG_TOO_LONG → refresh 补证据重排 → 仍失败转 ReAct
# ---------------------------------------------------------------------------

def test_t3_route_too_long_refresh_then_react(
    service, monkeypatch, image_recorders, final_validate_recorder
):
    draft = make_plan()
    react_plan = make_plan(attraction_name="ReAct景点")
    search_calls = []
    validate_calls = []

    def fake_prepare(self):
        return True

    def fake_validate(self, input_text):
        validate_calls.append(input_text)
        # 与真实 validate_draft 一致：不通过时计划保持 draft 状态（状态机写入点）
        self.session.plan = draft
        draft.status = "draft"
        return json.dumps(
            {
                "passed": False,
                "issues": [{"code": "ROUTE_LEG_TOO_LONG", "message": "相邻节点距离过大"}],
            },
            ensure_ascii=False,
        )

    def fake_search(self, input_text):
        payload = json.loads(input_text)
        search_calls.append(payload)
        return json.dumps({"source": "amap", "candidates": []}, ensure_ascii=False)

    monkeypatch.setattr(PlanningToolset, "prepare_required_evidence", fake_prepare)
    monkeypatch.setattr(PlanningToolset, "validate_draft", fake_validate)
    monkeypatch.setattr(PlanningToolset, "search_poi", fake_search)

    build_calls = []

    def fake_build(request, session):
        build_calls.append(session)
        return draft

    monkeypatch.setattr(service, "_build_evidence_plan", fake_build)

    react_instances = install_react_agent(monkeypatch, react_plan)
    request = make_request()

    result = service.plan_trip(request)

    # refresh 各一次：餐馆 + 景点，且都带 refresh=true（:291-301）
    assert [call["purpose"] for call in search_calls] == ["meal", "attraction"]
    assert all(call.get("refresh") for call in search_calls)
    # 重排跑了两轮（首轮 + refresh 后重试）
    assert len(build_calls) == 2
    # 仍失败 → 转 ReAct 兜底，交付 ReAct 产出的计划
    assert len(react_instances) == 1
    assert result is react_plan
    assert len(final_validate_recorder) == 1


# ---------------------------------------------------------------------------
# T4 Chroma 召回超时：主线程继续走高德预取，后台向量查询放行热身
# ---------------------------------------------------------------------------

def test_t4_chroma_timeout_proceeds_without_waiting(
    service, monkeypatch, image_recorders, final_validate_recorder
):
    settings = get_settings()
    monkeypatch.setattr(settings, "planner_vector_retrieval_timeout_seconds", 0.2)

    # 区县请求才会进入 Chroma 召回分支（:183 市级直接跳过）
    import app.services.amap_service as amap_module
    fake_amap = FakeAmap(adcode="440307", center=(114.346, 22.695), search_city="深圳")
    monkeypatch.setattr(amap_module, "get_amap_service", lambda: fake_amap)

    chroma_calls = []

    def slow_chroma(request, preference, adcode=None, amap_city=None):
        chroma_calls.append({"adcode": adcode, "amap_city": amap_city})
        time.sleep(1.0)  # 远超 0.2s 预算，模拟嵌入模型冷启动
        return [{"poi_id": "slow", "poi_group": "attraction"}]

    monkeypatch.setattr(
        tps.TripPlanningService, "_retrieve_cached_pois", staticmethod(slow_chroma)
    )

    draft = make_plan(city="深圳坪山")
    install_passing_toolset(monkeypatch, service, draft)
    react_instances = install_react_agent(monkeypatch, make_plan(), deliver=False)

    request = make_request(city="深圳坪山")
    started = time.perf_counter()
    result = service.plan_trip(request)
    elapsed = time.perf_counter() - started

    # 不等待慢速 Chroma：耗时必须远小于 1.0s 的睡眠
    assert elapsed < 0.9, f"plan_trip 等待了慢速 Chroma 召回（{elapsed:.2f}s）"
    # 召回带着区县 adcode 发起（:190-196）
    assert chroma_calls == [{"adcode": "440307", "amap_city": "深圳"}]
    # 超时后 cached_pois 为空，走高德预取路径，仍能交付确定性计划
    assert chroma_calls and result is draft
    assert react_instances == []


# ---------------------------------------------------------------------------
# T5 定向修改/预加载证据模式跳过图片补齐
# ---------------------------------------------------------------------------

def test_t5_preloaded_mode_skips_image_enrichment(
    service, monkeypatch, image_recorders, final_validate_recorder
):
    draft = make_plan()
    install_passing_toolset(monkeypatch, service, draft)
    meal_calls, image_calls = image_recorders

    request = make_request()  # 无 current_plan → 跳过原因只能是"预加载证据"
    result = service.plan_trip(request)

    assert result is draft
    assert meal_calls == [draft], "预加载证据模式应走 _enrich_meal_pois 而非图片补齐"
    assert image_calls == [], "预加载证据模式必须跳过图片补齐（CLAUDE.md 明文约定）"


def test_t5_targeted_full_replan_skips_image_enrichment(
    service, monkeypatch, image_recorders, final_validate_recorder
):
    draft = make_plan(attraction_name="全量重排后的新景点")
    install_passing_toolset(monkeypatch, service, draft)
    meal_calls, image_calls = image_recorders

    request = make_request(
        current_plan=make_plan_dict(),
        # full_replan 不走 _execute_change_set，但 current_plan+change_set
        # 仍构成"定向修改"上下文（:372）
        change_set=ChangeSet(operations=[ChangeOperation(operation="full_replan")]),
    )
    result = service.plan_trip(request)

    assert result is draft
    assert meal_calls == [draft], "定向修改上下文应走 _enrich_meal_pois"
    assert image_calls == [], "定向修改模式必须跳过图片补齐（CLAUDE.md 明文约定）"


# ---------------------------------------------------------------------------
# T6 ReAct 结束但无 Validator 通过的计划 → RuntimeError
# ---------------------------------------------------------------------------

def test_t6_react_without_validated_plan_raises(
    service, monkeypatch, image_recorders, final_validate_recorder
):
    settings = get_settings()
    monkeypatch.setattr(settings, "planner_preload_poi_evidence", False)

    # deliver=False：run 返回了文本，但没有任何 Draft 通过 Validator
    react_instances = install_react_agent(monkeypatch, make_plan(), deliver=False)

    def forbidden_build(*args, **kwargs):
        raise AssertionError("证据未预加载时不应触发确定性排程")

    monkeypatch.setattr(service, "_build_evidence_plan", forbidden_build)
    request = make_request()

    with pytest.raises(RuntimeError, match="没有通过 Validator 的旅行计划"):
        service.plan_trip(request)

    assert len(react_instances) == 1


def test_t6b_react_draft_status_plan_is_not_delivered(
    service, monkeypatch, image_recorders, final_validate_recorder
):
    """状态机门禁：计划实例存在但 status 仍是 draft 时，同样禁止交付。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "planner_preload_poi_evidence", False)

    # deliver="draft"：计划实例已放入 session.plan，但状态未过 Validator
    react_instances = install_react_agent(monkeypatch, make_plan(), deliver="draft")

    def forbidden_build(*args, **kwargs):
        raise AssertionError("证据未预加载时不应触发确定性排程")

    monkeypatch.setattr(service, "_build_evidence_plan", forbidden_build)
    request = make_request()

    with pytest.raises(RuntimeError, match="没有通过 Validator 的旅行计划"):
        service.plan_trip(request)

    assert len(react_instances) == 1


# ---------------------------------------------------------------------------
# T7 工具封装：Tool 类注册后提示词描述与入参协议逐字节不变
# ---------------------------------------------------------------------------

EXPECTED_TOOLS_DESCRIPTION = (
    "- search_poi: 先搜索对应大类的 Chroma 候选；结果不足时设置 refresh=true 调高德。"
    "输入单行 JSON: purpose, query, category, refresh(可选)\n"
    "- validate_draft: 校验完整 TripPlan Draft；输入单行 TripPlan JSON"
)


def test_t7_tool_description_byte_identical(monkeypatch):
    """get_tools_description() 输出逐字节等于原 register_function 时代的字符串。"""
    from app.services.planning_service import (
        PlanningSession,
        ValidatedPlanningReActAgent,
    )

    request = make_request()
    session = PlanningSession(
        request=request,
        city_center=None,
        radius_km=10.0,
        target_adcode=None,
        amap_city="北京",
    )
    agent = ValidatedPlanningReActAgent(llm=FakeLLM(), session=session)
    assert agent.tool_registry.get_tools_description() == EXPECTED_TOOLS_DESCRIPTION


def test_t7_tool_input_passthrough(monkeypatch):
    """execute_tool 把原始输入字符串原样传给 PlanningToolset 方法。"""
    from app.services.planning_service import (
        PlanningSession,
        PlanningToolset,
        ValidatedPlanningReActAgent,
    )

    request = make_request()
    session = PlanningSession(
        request=request,
        city_center=None,
        radius_km=10.0,
        target_adcode=None,
        amap_city="北京",
    )
    received = []
    monkeypatch.setattr(
        PlanningToolset, "search_poi", lambda self, input_text: received.append(input_text) or "ok"
    )
    monkeypatch.setattr(
        PlanningToolset, "validate_draft",
        lambda self, input_text: received.append(input_text) or "ok",
    )
    agent = ValidatedPlanningReActAgent(llm=FakeLLM(), session=session)

    assert agent.tool_registry.execute_tool("search_poi", "A") == "ok"
    assert agent.tool_registry.execute_tool("validate_draft", "B") == "ok"
    assert received == ["A", "B"]
