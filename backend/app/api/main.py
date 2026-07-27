"""FastAPI主应用"""

import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ..config import get_settings, validate_config, print_config
from ..database import database_health, init_database
from ..services.poi_vector_store import get_poi_vector_store
from .routes import trip, poi, map as map_routes, auth, conversations, talk

# 获取配置
settings = get_settings()

# 创建FastAPI应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="行旅天下 - 基于HelloAgents框架的智能旅行规划助手API",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(trip.router, prefix="/api")
app.include_router(poi.router, prefix="/api")
app.include_router(map_routes.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(talk.router, prefix="/api")


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    print("\n" + "="*60)
    print(f"{settings.app_name} v{settings.app_version}")
    print("="*60)
    
    # 打印配置信息
    print_config()
    
    # 验证配置
    try:
        validate_config()
        print("\n配置验证通过")
    except ValueError as e:
        print(f"\n配置验证失败:\n{e}")
        print("\n请检查.env文件并确保所有必要的配置项都已设置")
        raise

    await init_database()

    # Chroma 在后端启动阶段预热，避免首个规划请求承担 PersistentClient
    # 和 collection 初始化耗时。Chroma 不可用时保持 REST/MCP 降级链路。
    chroma_started = asyncio.get_running_loop().time()
    chroma_store = await asyncio.to_thread(get_poi_vector_store)
    chroma_elapsed_ms = round(
        (asyncio.get_running_loop().time() - chroma_started) * 1000,
        3,
    )
    if chroma_store is not None:
        print(f"Chroma 启动预热完成，耗时 {chroma_elapsed_ms:.3f} ms")
    else:
        print(
            f"Chroma 启动预热失败，耗时 {chroma_elapsed_ms:.3f} ms；"
            "后续使用 REST/MCP 降级链路"
        )
    
    print("\n" + "="*60)
    print("API文档: http://localhost:8000/docs")
    print("ReDoc文档: http://localhost:8000/redoc")
    print("="*60 + "\n")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    print("\n" + "="*60)
    print("应用正在关闭...")
    print("="*60 + "\n")


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "database": "connected" if await database_health() else "not_configured_or_unavailable"
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )

