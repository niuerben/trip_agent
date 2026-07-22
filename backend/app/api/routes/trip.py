"""旅行规划 API 路由。"""

import asyncio

from fastapi import APIRouter, HTTPException

from ...agents.trip_planner_agent import MultiAgentTripPlanner, get_trip_planner_agent
from ...config import get_settings
from ...models.schemas import TripPlan, TripPlanResponse, TripRequest

router = APIRouter(prefix="/trip", tags=["旅行规划"])


@router.post(
    "/plan",
    response_model=TripPlanResponse,
    summary="生成旅行计划",
    description="根据用户输入的旅行需求，生成详细的旅行计划",
)
async def plan_trip(request: TripRequest):
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

        if not has_llm_key:
            print("未配置模型密钥，直接使用基础计划")
            trip_plan = MultiAgentTripPlanner._create_fallback_plan(
                request,
                "未配置模型密钥",
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
                    asyncio.to_thread(agent.plan_trip, request),
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
