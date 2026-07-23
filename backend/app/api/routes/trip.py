"""旅行规划 API 路由。"""

import asyncio

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from ...agents.trip_planner_agent import MultiAgentTripPlanner, get_trip_planner_agent
from ...config import get_settings
from ...database import engine
from ...models.schemas import Preference, TripPlan, TripPlanResponse, TripRequest
from .conversations import user_id_from_request

router = APIRouter(prefix="/trip", tags=["旅行规划"])


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


@router.post(
    "/plan",
    response_model=TripPlanResponse,
    summary="生成旅行计划",
    description="根据用户输入的旅行需求，生成详细的旅行计划",
)
async def plan_trip(request: TripRequest, http_request: Request):
    """生成旅行计划；模型或 MCP 不可用时返回可用的基础计划。"""
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

        if not has_llm_key:
            print("未配置模型密钥，直接使用基础计划")
            trip_plan = MultiAgentTripPlanner._create_fallback_plan(
                request,
                "未配置模型密钥",
                preference,
            )
            trip_plan = MultiAgentTripPlanner._enrich_attraction_images(trip_plan)
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
            except Exception as agent_error:
                print(
                    "模型服务不可用，使用基础计划: "
                    f"{type(agent_error).__name__}: {agent_error}"
                )
                trip_plan = MultiAgentTripPlanner._create_fallback_plan(
                    request,
                    "模型或高德服务响应超时/不可用",
                    preference,
                )
                trip_plan = MultiAgentTripPlanner._enrich_attraction_images(trip_plan)

        print("旅行计划生成成功，准备返回响应\n")
        return TripPlanResponse(
            success=True,
            message="旅行计划生成成功",
            data=trip_plan,
        )
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
    """为历史计划中缺少 image_url 的景点补充高德 POI 图片。"""
    enriched_plan = await asyncio.to_thread(
        MultiAgentTripPlanner._enrich_attraction_images,
        plan,
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
            "agent_name": agent.agent.name,
            "tools_count": len(agent.agent.list_tools()),
        }
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"服务不可用: {error}") from error
