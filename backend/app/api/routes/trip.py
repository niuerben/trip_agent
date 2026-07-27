"""旅行规划 API 路由。"""

import asyncio
import json
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from ...agents.trip_planner_agent import (
    TripPlannerAgent,
    _is_district_request,
    get_trip_planner_agent,
)
from ...config import get_settings
from ...database import engine
from ...models.schemas import Preference, TripPlan, TripPlanResponse, TripRequest
from ...services.trip_plan_validator import validate_trip_plan
from .conversations import user_id_from_request

router = APIRouter(prefix="/trip", tags=["旅行规划"])
_PLANNER_LOG_LOCK = threading.Lock()
_BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _write_planner_input_log(
    request: TripRequest,
    preference: Preference,
    preference_source: str,
) -> None:
    """记录实际传入规划链路的完整当前计划，便于人工调试提示词。"""
    settings = get_settings()
    path = Path(settings.planner_input_log_path)
    if not path.is_absolute():
        # routes/ → api/ → app/ → backend/
        path = Path(__file__).resolve().parents[3] / path
    payload = {
        "timestamp": datetime.now(_BEIJING_TZ).isoformat(timespec="seconds"),
        "event": "planner_input",
        "conversation_id": request.conversation_id,
        "city": request.city,
        "start_date": str(request.start_date),
        "end_date": str(request.end_date),
        "travel_days": request.travel_days,
        "change_request": request.change_request,
        "change_set": request.change_set.model_dump() if request.change_set else None,
        "free_text_input": request.free_text_input,
        "preference_source": preference_source,
        "preference_prompt": preference.prompt,
        "current_plan": request.current_plan,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _PLANNER_LOG_LOCK:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception as error:
        print(f"规划输入日志写入失败: {type(error).__name__}: {error}")


def _write_planner_review_log(
    *,
    status: str,
    request: TripRequest,
    preference: Preference,
    preference_source: str,
    plan: TripPlan | None = None,
    error: Exception | str | None = None,
) -> None:
    """记录每次规划交付给 Validator 的完整上下文与最终结果。

    Talk Agent 不参与规划结果审核；它只负责对话语义和偏好。因此日志明确
    标记实际审查者为 Validator，避免把不存在的 Agent 间调用写成事实。
    """
    settings = get_settings()
    path = Path(settings.planner_review_log_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    payload = {
        "timestamp": datetime.now(_BEIJING_TZ).isoformat(timespec="seconds"),
        "event": "planner_delivery_review",
        "status": status,
        "reviewer": "trip_plan_validator",
        "conversation_id": request.conversation_id,
        "request": {
            "city": request.city,
            "start_date": str(request.start_date),
            "end_date": str(request.end_date),
            "travel_days": request.travel_days,
            "transportation": request.transportation,
            "accommodation": request.accommodation,
            "preferences": request.preferences,
            "free_text_input": request.free_text_input,
            "change_request": request.change_request,
            "change_set": request.change_set.model_dump() if request.change_set else None,
            "current_plan": request.current_plan,
        },
        "preference_source": preference_source,
        "preference_prompt": preference.prompt,
        "trip_plan": plan.model_dump() if plan else None,
        "error": str(error) if error else None,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _PLANNER_LOG_LOCK:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception as log_error:
        print(f"规划交付审查日志写入失败: {type(log_error).__name__}: {log_error}")


async def _load_conversation_preference(conversation_id: str | None, user_id: str) -> Preference | None:
    """按当前用户读取 talk_agent 已提炼并保存的偏好。"""
    if not conversation_id or engine is None:
        return None
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("""
                SELECT prompt
                FROM conversation_preferences
                WHERE conversation_id = :conversation_id AND user_id = :user_id
            """), {"conversation_id": conversation_id, "user_id": user_id})
            row = result.first()
    except Exception as error:
        print(f"读取会话偏好失败，使用请求兜底: {type(error).__name__}: {error}")
        return None
    return Preference(prompt=row.prompt) if row and row.prompt else None


async def _persist_changed_plan(conversation_id: str | None, user_id: str, plan: TripPlan) -> None:
    """使用参数化 SQL 将已校验的 ChangeSet 执行结果写回当前用户会话。"""
    if not conversation_id or engine is None:
        return
    async with engine.begin() as connection:
        await connection.execute(text("""
            UPDATE conversations
            SET payload = CAST(:payload AS JSONB), updated_at = NOW()
            WHERE id = :conversation_id AND user_id = :user_id
        """), {
            "payload": json.dumps(plan.model_dump(), ensure_ascii=False),
            "conversation_id": conversation_id,
            "user_id": user_id,
        })


@router.post(
    "/plan",
    response_model=TripPlanResponse,
    summary="生成旅行计划",
    description="根据用户输入的旅行需求，生成详细的旅行计划",
)
async def plan_trip(request: TripRequest, http_request: Request):
    """生成旅行计划；只有通过 ReAct Validator 的计划才允许出站。"""
    try:
        print(f"\n{'=' * 60}")
        print("收到旅行规划请求:")
        print(f"   城市: {request.city}")
        print(f"   日期: {request.start_date} - {request.end_date}")
        print(f"   天数: {request.travel_days}")
        print(f"{'=' * 60}\n")

        settings = get_settings()
        has_llm_key = (
            settings.planner_mode.lower() != "fallback"
            and bool(settings.llm_api_key or settings.openai_api_key)
        )

        user_id = user_id_from_request(http_request)
        preference = request.preference
        preference_source = "request.preference"
        if preference is None:
            preference = await _load_conversation_preference(
                request.conversation_id,
                user_id,
            )
            preference_source = "talk_agent.conversation"
        if preference is None:
            preference = Preference(prompt=request.free_text_input or "")
            preference_source = "request.free_text_input"
        print(
            f"偏好来源: {preference_source}; "
            f"内容: {(preference.prompt or '无')[:120]}"
        )
        print(
            f"语义规划: {'定向修改' if request.current_plan and request.change_request else '首次/完整规划'}; "
            f"conversation_id: {request.conversation_id or '无'}"
        )
        _write_planner_input_log(request, preference, preference_source)

        if not has_llm_key:
            _write_planner_review_log(
                status="rejected",
                request=request,
                preference=preference,
                preference_source=preference_source,
                error="未配置模型密钥",
            )
            raise HTTPException(
                status_code=503,
                detail="未配置模型密钥，无法生成经过 Validator 验证的旅行计划",
            )
        else:
            try:
                agent = await asyncio.wait_for(
                    asyncio.to_thread(get_trip_planner_agent),
                    timeout=settings.planner_init_timeout_seconds,
                )
                print("开始生成旅行计划...")
                trip_plan = await asyncio.wait_for(
                    asyncio.to_thread(agent.plan_trip, request, preference),
                    timeout=settings.planner_execution_timeout_seconds,
                )
            except asyncio.TimeoutError as timeout_error:
                agent_error = RuntimeError(
                    f"旅行规划超过 {settings.planner_execution_timeout_seconds} 秒总预算"
                )
                message = (
                    "定向重规划未完成，原计划保持不变"
                    if request.current_plan
                    else "旅行计划未通过 ReAct + Validator"
                )
                _write_planner_review_log(
                    status="rejected",
                    request=request,
                    preference=preference,
                    preference_source=preference_source,
                    error=agent_error,
                )
                raise HTTPException(
                    status_code=504,
                    detail=f"{message}: {agent_error}",
                ) from timeout_error
            except Exception as agent_error:
                message = (
                    "定向重规划未完成，原计划保持不变"
                    if request.current_plan
                    else "旅行计划未通过 ReAct + Validator"
                )
                _write_planner_review_log(
                    status="rejected",
                    request=request,
                    preference=preference,
                    preference_source=preference_source,
                    error=agent_error,
                )
                raise HTTPException(
                    status_code=422,
                    detail=f"{message}: {agent_error}",
                ) from agent_error

        # ReAct 内部校验后，路由出站前再执行一次独立业务校验。
        validate_trip_plan(trip_plan, request, require_enriched_locations=True)
        _write_planner_review_log(
            status="approved",
            request=request,
            preference=preference,
            preference_source=preference_source,
            plan=trip_plan,
        )
        if request.change_set:
            await _persist_changed_plan(request.conversation_id, user_id, trip_plan)
        print("旅行计划生成成功，准备返回响应\n")
        return TripPlanResponse(
            success=True,
            message="旅行计划生成成功",
            data=trip_plan,
        )
    except HTTPException:
        raise
    except Exception as error:
        print(f"生成旅行计划失败: {error}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"生成旅行计划失败: {error}",
        ) from error


@router.post(
    "/enrich-images",
    response_model=TripPlanResponse,
    summary="补齐行程景点图片",
)
async def enrich_trip_images(plan: TripPlan):
    """为历史计划补齐 POI 图片、坐标及缺失旅行日天气。"""
    settings = get_settings()
    city_center = None
    target_adcode = None
    try:
        from ...services.amap_service import get_amap_service

        amap_service = get_amap_service()
        city_center = amap_service.get_city_center(plan.city)
        if _is_district_request(plan.city):
            target_adcode = amap_service.get_city_adcode(plan.city)
    except Exception as error:
        print(f"历史计划行政区解析失败: {type(error).__name__}: {error}")
    radius_km = (
        settings.district_geo_radius_km
        if _is_district_request(plan.city)
        else settings.city_geo_radius_km
    )
    requires_poi_enrichment = any(
        not attraction.poi_id
        for day in plan.days
        for attraction in day.attractions
    ) or any(
        not meal.poi_id or meal.location is None
        for day in plan.days
        for meal in day.meals
    )
    if requires_poi_enrichment:
        enriched_plan = await asyncio.to_thread(
            TripPlannerAgent._enrich_attraction_images,
            plan,
            city_center,
            radius_km,
            target_adcode,
        )
    else:
        # 仅补天气的历史会话不再重复执行 POI 图片/坐标查询。
        enriched_plan = plan.model_copy(deep=True)
    # 历史会话可能保留了旧版“从今天起”的天气数组。只对缺失旅行日
    # 进行精确补查，不重拉已经存在的高德预报。
    first_day = enriched_plan.days[0] if enriched_plan.days else None
    weather_request = TripRequest(
        city=enriched_plan.city,
        start_date=enriched_plan.start_date,
        end_date=enriched_plan.end_date,
        travel_days=len(enriched_plan.days),
        transportation=first_day.transportation if first_day else "公共交通",
        accommodation=first_day.accommodation if first_day else "经济型酒店",
    )
    enriched_plan.weather_info = await asyncio.to_thread(
        TripPlannerAgent._complete_weather_for_travel_dates,
        enriched_plan.weather_info,
        weather_request,
        city_center,
    )
    for day in enriched_plan.days:
        for attraction in day.attractions:
            if any(marker in attraction.name for marker in ("大学", "学院", "学校", "校园")):
                print(
                    "高德 POI 出站坐标: "
                    f"{attraction.name} | {attraction.address} | "
                    f"{attraction.location.longitude},{attraction.location.latitude} | "
                    f"poi_id={attraction.poi_id or '无'}"
                )
    return TripPlanResponse(
        success=True,
        message="景点图片补齐成功",
        data=enriched_plan,
    )


@router.get(
    "/health",
    summary="健康检查",
    description="检查旅行规划服务是否正常",
)
async def health_check():
    """检查规划 Agent 是否可以初始化。"""
    try:
        agent = await asyncio.wait_for(
            asyncio.to_thread(get_trip_planner_agent),
            timeout=get_settings().planner_init_timeout_seconds,
        )
        return {
            "status": "healthy",
            "service": "trip-planner",
            "agent_name": agent.agent_name,
            "tools_count": agent.tools_count,
        }
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"服务不可用: {error}") from error
