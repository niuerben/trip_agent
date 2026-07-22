"""LLM服务模块"""

import os

from hello_agents import HelloAgentsLLM
from ..config import get_settings

# 全局LLM实例
_llm_instance = None


def get_llm() -> HelloAgentsLLM:
    """
    获取LLM实例(单例模式)
    
    Returns:
        HelloAgentsLLM实例
    """
    global _llm_instance
    
    if _llm_instance is None:
        settings = get_settings()

        # HelloAgentsLLM读取OPENAI_*环境变量，兼容项目使用的LLM_*命名。
        if not os.getenv("OPENAI_API_KEY") and os.getenv("LLM_API_KEY"):
            os.environ["OPENAI_API_KEY"] = os.environ["LLM_API_KEY"]
        if not os.getenv("OPENAI_BASE_URL") and os.getenv("LLM_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = os.environ["LLM_BASE_URL"]
        if not os.getenv("OPENAI_MODEL") and os.getenv("LLM_MODEL_ID"):
            os.environ["OPENAI_MODEL"] = os.environ["LLM_MODEL_ID"]
        
        # HelloAgentsLLM会自动从环境变量读取配置
        # 包括OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL等
        _llm_instance = HelloAgentsLLM()
        
        print(f"✅ LLM服务初始化成功")
        print(f"   提供商: {_llm_instance.provider}")
        print(f"   模型: {_llm_instance.model}")
    
    return _llm_instance


def reset_llm():
    """重置LLM实例(用于测试或重新配置)"""
    global _llm_instance
    _llm_instance = None

