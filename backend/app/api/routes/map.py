"""地图服务API路由"""

import asyncio
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from ...models.schemas import (
    POISearchRequest,
    POISearchResponse,
    RouteRequest,
    RouteResponse,
    WeatherResponse
)
from ...services.amap_service import get_amap_service

router = APIRouter(prefix="/map", tags=["地图服务"])


def _parse_coordinate(value: str, field_name: str):
    from ...models.schemas import Location

    try:
        longitude, latitude = (float(item.strip()) for item in value.split(",", 1))
    except (AttributeError, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"{field_name} 必须为 longitude,latitude") from error
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise HTTPException(status_code=422, detail=f"{field_name} 坐标超出范围")
    return Location(longitude=longitude, latitude=latitude)


@router.get(
    "/poi",
    response_model=POISearchResponse,
    summary="搜索POI",
    description="根据关键词搜索POI(兴趣点)"
)
async def search_poi(
    keywords: str = Query(..., description="搜索关键词", examples=["故宫"]),
    city: str = Query(..., description="城市", examples=["北京"]),
    citylimit: bool = Query(True, description="是否限制在城市范围内")
):
    """
    搜索POI
    
    Args:
        keywords: 搜索关键词
        city: 城市
        citylimit: 是否限制在城市范围内
        
    Returns:
        POI搜索结果
    """
    try:
        # 获取服务实例
        service = get_amap_service()
        
        # 搜索POI
        pois = service.search_poi(keywords, city, citylimit)
        
        return POISearchResponse(
            success=True,
            message="POI搜索成功",
            data=pois
        )
        
    except Exception as e:
        print(f"❌ POI搜索失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"POI搜索失败: {str(e)}"
        )


@router.get(
    "/weather",
    response_model=WeatherResponse,
    summary="查询天气",
    description="查询指定城市的天气信息"
)
async def get_weather(
    city: str = Query(..., description="城市名称", examples=["北京"])
):
    """
    查询天气
    
    Args:
        city: 城市名称
        
    Returns:
        天气信息
    """
    try:
        # 获取服务实例
        service = get_amap_service()
        
        # 查询天气
        weather_info = service.get_weather(city)
        
        return WeatherResponse(
            success=True,
            message="天气查询成功",
            data=weather_info
        )
        
    except Exception as e:
        print(f"❌ 天气查询失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"天气查询失败: {str(e)}"
        )


@router.post(
    "/route",
    response_model=RouteResponse,
    summary="规划路线",
    description="规划两点之间的路线"
)
async def plan_route(request: RouteRequest):
    """
    规划路线
    
    Args:
        request: 路线规划请求
        
    Returns:
        路线信息
    """
    try:
        # 获取服务实例
        service = get_amap_service()
        
        # 规划路线
        route_info = service.plan_route(
            origin_address=request.origin_address,
            destination_address=request.destination_address,
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            route_type=request.route_type
        )
        return RouteResponse(
            success=True,
            message="路线规划成功",
            data=route_info
        )
        
    except Exception as e:
        print(f"❌ 路线规划失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"路线规划失败: {str(e)}"
        )


@router.get(
    "/route-geometry",
    summary="获取道路与公共交通路线几何",
)
async def route_geometry(
    origin: str = Query(..., description="起点，经度,纬度"),
    destination: str = Query(..., description="终点，经度,纬度"),
    city: str = Query(..., description="公共交通所在城市"),
    route_type: str = Query("driving", pattern="^(driving|transit)$"),
):
    """为前端地图返回真实道路或地铁/公交折线；路线服务异常时返回 502。"""
    try:
        result = await asyncio.to_thread(
            get_amap_service().get_route_geometry,
            _parse_coordinate(origin, "origin"),
            _parse_coordinate(destination, "destination"),
            city,
            route_type,
        )
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"路线几何查询失败: {error}") from error


@router.get(
    "/health",
    summary="健康检查",
    description="检查地图服务是否正常"
)
async def health_check():
    """健康检查"""
    try:
        # 检查服务是否可用
        service = get_amap_service()
        
        return {
            "status": "healthy",
            "service": "map-service",
            "mcp_tools_count": (
                len(service.mcp_tool._available_tools)
                if service.mcp_tool is not None
                else 0
            ),
            "rest_api_configured": bool(service.api_key),
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"服务不可用: {str(e)}"
        )

