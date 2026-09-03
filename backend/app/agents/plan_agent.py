"""Planning layer defined by ``spec/spec2code.md``."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from hello_agents import ReActAgent, ToolRegistry
from hello_agents.agents import SimpleAgent

from .tool_lib import SearchAttraction, SearchHotel, SearchRestaurant, SearchWeather
from ..services.llm_service import get_llm

from .search_agent import (
    HotelAgent,
    RestaurantAgent,
    WeatherAgent,
)
from .validate_agent import ValidateAgent

PLAN_PROMPT = """你是一个具备推理和行动能力的AI助手。你可以通过思考分析问题，然后调用合适的工具来获取信息，最终给出准确的答案。

## 可用工具
{tools}

## 工作流程
请严格按照以下格式进行回应，每次只能执行一个步骤：

Thought: 分析问题，确定需要什么信息，制定研究策略。
Action: 选择合适的工具获取信息，格式为：
- `{{tool_name}}[{{tool_input}}]`：调用工具获取信息。
- `Finish[TalkResponse]`：当你有足够信息得出结论时。TalkResponse为JSON格式，schema 如下
    success: bool = Field(default=True, description="是否成功")
    reply: str = Field(default="", description="assistant 回复")
    intent: str = Field(default="chat", description="语义意图: chat / replan")
    change_request: Optional[str] = Field(default=None, description="提炼后的行程修改要求")
    change_set: Optional[ChangeSet] = Field(default=None, description="LLM 输出的结构化计划操作")
    top_suggestions: List[str] = Field(default_factory=list, description="基于当前会话记忆生成的 3 条后续建议")
    preference: Optional["Preference"] = Field(default=None, description="提炼出的偏好")
    done: bool = Field(default=False, description="偏好是否收集完成")
    messages: List[ChatMessage] = Field(default=[], description="持久化后的完整聊天记录")

## 重要提醒
1. 每次回应必须包含Thought和Action两部分
2. 工具调用的格式必须严格遵循：工具名[参数]
3. 只有当你确信有足够信息回答问题时，才使用Finish
4. 如果工具返回的信息不够，继续使用其他工具或相同工具的不同参数

## 当前任务
**Question:** {question}

## 执行历史
{history}

现在开始你的推理和行动："""

class PlanAgent(SimpleAgent):
    """ 通过 ReAct 循环，完成旅行规划 """

    def __init__(self) -> None:
        self.llm = get_llm()

        self.search_agents = {
            "search_weather": WeatherAgent(),
            "search_hotel": HotelAgent(),
            "search_restaurant": RestaurantAgent(),
        }
        self.validate_agent = ValidateAgent()    
        self.result: Any = None

        tool_registry = ToolRegistry()
        tool_registry.register_tool(SearchAttraction())
        tool_registry.register_tool(SearchWeather())
        tool_registry.register_tool(SearchHotel())
        tool_registry.register_tool(SearchRestaurant())
        self.react_agent = ReActAgent("旅行规划师",self.llm,tool_registry,max_steps=8, custom_prompt=PLAN_PROMPT)

    def run(self, input_text: str, max_tool_iterations: int=3, **kwargs) -> str:
        response = self.react_agent.run(input_text) 
        return response

