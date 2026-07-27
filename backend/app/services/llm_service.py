"""LLM服务模块"""

import os
from types import MethodType

from hello_agents import HelloAgentsLLM
from hello_agents.core.exceptions import HelloAgentsException
from openai import OpenAI
from ..config import get_settings


# 全局LLM实例
_llm_instance = None


def _streaming_invoke(self, messages: list[dict[str, str]], **kwargs) -> str:
    """流式累积模型输出，避免长 JSON 在服务端生成时触发整包读取超时。"""
    try:
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            stream=True,
            **{
                key: value
                for key, value in kwargs.items()
                if key not in {"temperature", "max_tokens", "stream"}
            },
        )
        parts: list[str] = []
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            content = getattr(choices[0].delta, "content", None)
            if content:
                parts.append(content)
        return "".join(parts)
    except Exception as error:
        raise HelloAgentsException(f"LLM调用失败: {error}") from error


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
        _llm_instance = HelloAgentsLLM(
            timeout=settings.llm_timeout_seconds,
            max_tokens=settings.llm_max_tokens,
        )
        # OpenAI SDK 默认会对超时重试两次；在 API 总预算只有 60 秒的场景，
        # 这会把一次 45/55 秒的失败扩大到 135/165 秒，且 asyncio 无法取消
        # 已阻塞的同步线程。规划请求只允许一次模型 HTTP 尝试。
        _llm_instance._client = OpenAI(
            api_key=_llm_instance.api_key,
            base_url=_llm_instance.base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        # 非流式 OpenAI 调用会在完整 JSON 生成前一直等待响应体；三天行程的
        # JSON 较长，服务端虽已持续生成却可能超过 read timeout。改为流式累积，
        # 保持同一次模型调用并允许每个增量刷新读取超时。
        _llm_instance.invoke = MethodType(_streaming_invoke, _llm_instance)
        
        print("LLM服务初始化成功")
        print(f"   提供商: {_llm_instance.provider}")
        print(f"   模型: {_llm_instance.model}")
    
    return _llm_instance


def reset_llm():
    """重置LLM实例(用于测试或重新配置)"""
    global _llm_instance
    _llm_instance = None

