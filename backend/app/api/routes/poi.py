"""POI相关API路由"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from ...services.amap_service import get_amap_service
from ...services.amap_photo_service import get_amap_photo_service

router = APIRouter(prefix="/poi", tags=["POI"])


class POIDetailResponse(BaseModel):
    """POI详情响应"""
    success: bool
    message: str
    data: Optional[dict] = None


@router.get(
    "/detail/{poi_id}",
    response_model=POIDetailResponse,
    summary="获取POI详情",
    description="根据POI ID获取详细信息"
)
async def get_poi_detail(poi_id: str):
    """获取POI详情"""
    try:
        amap_service = get_amap_service()
        result = amap_service.get_poi_detail(poi_id)

        return POIDetailResponse(
            success=True,
            message="获取POI详情成功",
            data=result
        )
    except Exception as e:
        print(f"❌ 获取POI详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取POI详情失败: {str(e)}")


@router.get(
    "/search",
    summary="搜索POI",
    description="根据关键词搜索POI"
)
async def search_poi(keywords: str, city: str = "北京"):
    """搜索POI"""
    try:
        amap_service = get_amap_service()
        result = amap_service.search_poi(keywords, city)

        return {"success": True, "message": "搜索成功", "data": result}
    except Exception as e:
        print(f"❌ 搜索POI失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"搜索POI失败: {str(e)}")


@router.get(
    "/photo",
    summary="获取景点图片",
    description="根据景点名称从高德地图获取官方图片"
)
async def get_attraction_photo(
    name: str = Query(..., description="景点名称"),
    city: str = Query("", description="所在城市, 建议传入以提升匹配精度"),
):
    """获取景点图片(高德关键词搜索, extensions=all)"""
    try:
        photo_service = get_amap_photo_service()

        # 优先带上城市搜索, 命中率更高; 拿不到再退化为无城市搜索
        photo_url = photo_service.get_photo_url(name, city=city)
        if not photo_url and city:
            photo_url = photo_service.get_photo_url(name, city="")

        return {
            "success": True,
            "message": "获取图片成功" if photo_url else "未找到匹配图片",
            "data": {
                "name": name,
                "city": city,
                "photo_url": photo_url,
            },
        }
    except Exception as e:
        print(f"❌ 获取景点图片失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取景点图片失败: {str(e)}")
