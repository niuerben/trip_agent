"""配置管理模块"""

import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载环境变量
# 首先尝试加载当前目录的.env
load_dotenv()

# 然后尝试加载HelloAgents的.env(如果存在)
helloagents_env = Path(__file__).parent.parent.parent.parent / "HelloAgents" / ".env"
if helloagents_env.exists():
    load_dotenv(helloagents_env, override=False)  # 不覆盖已有的环境变量


class Settings(BaseSettings):
    """应用配置"""

    # 应用基本配置
    app_name: str = "行旅天下"
    app_version: str = "1.0.0"
    debug: bool = False

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8000

    # PostgreSQL连接串通过环境变量 DATABASE_URL 注入，不在代码中保存密码
    database_url: str = ""

    # CORS配置 - 使用字符串,在代码中分割
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"

    # 高德地图API配置
    amap_api_key: str = ""

    # LLM配置 (从环境变量读取,由HelloAgents管理)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model_id: str = "gpt-4o-mini"
    planner_mode: str = "auto"
    planner_init_timeout_seconds: int = 180
    # 用户端预算为 60 秒；预留约 5 秒给 HTTP/前端收尾，后端在 55 秒
    # 时就返回明确的超时响应。
    planner_execution_timeout_seconds: int = 55
    planner_max_tool_iterations: int = 4
    planner_max_react_steps: int = 6
    planner_max_stalled_steps: int = 2
    # 无效响应允许重试次数；模型偶发空响应时多给几轮恢复机会，整体
    # 用户等待仍由 planner_execution_timeout_seconds 统一控制。
    planner_max_invalid_responses: int = 3
    # 同一 purpose 最多执行几次 refresh=true 的高德补查。
    planner_max_refresh_per_purpose: int = 1
    required_meal_types: str = "breakfast,lunch,dinner"
    planner_candidate_limit: int = 10
    # Chroma 冷启动/嵌入模型下载不可阻塞首次规划；超时后改走高德预取。
    planner_vector_retrieval_timeout_seconds: int = 3
    mcp_log_path: str = "logs/mcp_calls.log"
    planner_input_log_path: str = "logs/planner_inputs.log"
    planner_review_log_path: str = "logs/planner_reviews.log"
    agent_loop_log_path: str = "logs/agent_loop.log"
    # 必须小于 API 的整体 60 秒预算。同步 HTTP 调用无法被
    # asyncio.wait_for 可靠中断，因此在 LLM 客户端层先结束请求。
    llm_timeout_seconds: int = 50
    llm_max_tokens: int = 4096
    # 首次完整规划由后端预取三类 POI 证据，避免模型为每类证据各发起一次
    # 串行 ReAct 调用。仅把少量、字段最小化的候选交给模型。
    planner_preload_poi_evidence: bool = True
    # 首次完整规划在 POI 证据齐备时由后端组合成近邻路线，避免模型生成大段
    # JSON 占满 60 秒 API 预算。证据不足或定向修改仍使用 ReAct。
    planner_preloaded_deterministic_plan: bool = True
    planner_preloaded_candidate_limit: int = 4
    # 餐饮不能因候选过少而在三餐/多天中重复同一 POI；完整规划至少展示
    # 每个必需餐次一个候选。相邻日程节点超过该直线距离即要求重新编排。
    # 公共交通场景允许约 7 公里相邻跨片区；5 公里会把南山等狭长城区的
    # 合理地铁/公交行程误判为无可行计划。
    planner_max_daily_route_leg_km: float = 7.0
    chroma_persist_directory: str = "data/chroma"
    chroma_collection_name: str = "amap_pois"
    poi_vector_top_k: int = 10
    # Chroma 余弦距离阈值；距离越小越相似，超过阈值的候选转高德 POI。
    poi_vector_distance_threshold: float = 0.55
    # 高德 Web 服务请求超时。连接和读取分开配置，避免单次网络抖动拖垮整条规划链路。
    amap_connect_timeout_seconds: int = 5
    amap_read_timeout_seconds: int = 12
    amap_request_retries: int = 1
    # 景点坐标越界阈值(公里)。以高德解析出的城市中心为基准，超过该半径视为跨城/跨省错误
    # (如深圳计划里混入北京景点)，触发越界重查或降级。默认 150km 足以覆盖市域及近郊，
    # 又能拦住模型幻觉出的远距离地点。城域极大的直辖市可按需调大。
    city_geo_radius_km: float = 150.0
    # 输入包含具体区县时，使用更小的范围，避免“深圳坪山”漂移到南山等其他区。
    district_geo_radius_km: float = 25.0
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4"

    # JWT / OAuth配置
    jwt_secret: str = "change-me-in-production"
    jwt_expire_minutes: int = 60 * 24 * 7
    auth_username: str = "admin"
    auth_password: str = "admin123"
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = "http://localhost:8000/api/auth/github/callback"
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    wechat_redirect_uri: str = "http://localhost:8000/api/auth/wechat/callback"

    # 日志配置
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # 忽略额外的环境变量

    def get_cors_origins_list(self) -> List[str]:
        """获取CORS origins列表"""
        return [origin.strip() for origin in self.cors_origins.split(',')]


# 创建全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings


# 验证必要的配置
def validate_config():
    """验证配置是否完整"""
    errors = []
    warnings = []

    if not settings.amap_api_key:
        warnings.append("AMAP_API_KEY未配置，地图相关功能可能无法使用")

    # HelloAgentsLLM会自动从LLM_API_KEY读取,不强制要求OPENAI_API_KEY
    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not llm_api_key:
        warnings.append("LLM_API_KEY或OPENAI_API_KEY未配置,LLM功能可能无法使用")

    if errors:
        error_msg = "配置错误:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    if warnings:
        print("\n配置警告:")
        for w in warnings:
            print(f"  - {w}")

    return True


# 打印配置信息(用于调试)
def print_config():
    """打印当前配置(隐藏敏感信息)"""
    print(f"应用名称: {settings.app_name}")
    print(f"版本: {settings.app_version}")
    print(f"服务器: {settings.host}:{settings.port}")
    print(f"高德地图API Key: {'已配置' if settings.amap_api_key else '未配置'}")

    # 检查LLM配置
    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    llm_base_url = os.getenv("LLM_BASE_URL") or settings.openai_base_url
    llm_model = os.getenv("LLM_MODEL_ID") or settings.openai_model

    print(f"LLM API Key: {'已配置' if llm_api_key else '未配置'}")
    print(f"LLM Base URL: {llm_base_url}")
    print(f"LLM Model: {llm_model}")
    print(f"日志级别: {settings.log_level}")

