"""Planning layer defined by ``spec/spec2code.md``."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from hello_agents.agents import ReActAgent
from ..services.llm_service import get_llm
from ..tool.prompt_transform import (
    build_selection_prompt,
    normalise_selection_response,
    prompt_value,
)
from .search_agent import (
    AttractionAgent,
    HotelAgent,
    RestaurantAgent,
    SearchAgent,
    WeatherAgent,
)
from .validate_agent import ValidateAgent


class PlanningAgentError(RuntimeError):
    """The planning loop stopped without a validated result."""




SELECTION_PROMPT = """你是旅行规划专家。
你可根据用户需求选择需要的一个或多个 Search Agent， 利用返回的真实信息生成旅行计划。

信息充分后使用 finish 提交最终计划。finish.arguments.plan 使用紧凑 JSON，
包含三天行程、天气摘要、酒店、餐饮和预算摘要即可。
禁止编造工具未返回的地址、坐标、天气和价格。

只返回 JSON 对象，格式如下：
{"think": "本轮决策理由", "action": {"name": "工具名", "arguments": {}}}

每个搜索工具最多调用一次。在调用 finish 前，必须完成当前可用的景点、
天气、酒店和餐厅搜索；全部完成后，下一轮必须调用 finish，禁止继续搜索。
"""


class PlanAgent(ReActAgent):
    """ 通过 ReAct 循环，完成旅行规划 """

    def __init__(
        self,
        llm: Any = None,
        search_agents: Optional[Mapping[str, SearchAgent]] = None,
        validate_agent: Optional[ValidateAgent] = None,
        runner: Any = None,
        max_iterations: int = 8,
    ) -> None:
        self.llm = llm or get_llm()
        super().__init__(
            name="旅行规划 Agent",
            llm=self.llm,
            system_prompt=SELECTION_PROMPT,
            max_steps=max(1, max_iterations),
        )
        self.search_agents = (
            dict(search_agents)
            if search_agents is not None
            else {
                "search_attraction": AttractionAgent(),
                "search_weather": WeatherAgent(),
                "search_hotel": HotelAgent(),
                "search_restaurant": RestaurantAgent(),
            }
        )
        self.last_result: Any = None
        self.validate_agent = validate_agent or ValidateAgent()
        self.runner = runner
        self.max_iterations = max(1, max_iterations)
        self.observation: Any = None
        self.result: Any = None
        self.prompt = ""
        self.model_reasons: list[Any] = []
        self.selection_prompt = SELECTION_PROMPT

    def create_observation(self, requirement_prompt: str, preference_prompt: str, tool_result: Any = None) -> Any:
        if tool_result is not None:
            self.observation = tool_result
        elif self.observation is None:
            self.observation = {
                "requirement_prompt": requirement_prompt,
                "preference_prompt": preference_prompt,
            }
        return self.observation

    def plan(self, requirement_prompt: str, preference_prompt: str = "") -> Any:
        '''计划旅行

        Args:
            requirement_prompt: 旅行需求提示
            preference_prompt: 旅行偏好提示

        Returns:
            result: 计划结果，包含是否通过验证和最终计划
        '''
        if self.runner is not None:
            self.result = self.runner(requirement_prompt, preference_prompt)
            self.prompt = "Requirement: " + str(requirement_prompt or "") + "\nPreference: " + str(preference_prompt or "")
            return self.result

        prompt = "Requirement: " + str(requirement_prompt or "") + "\nPreference: " + str(preference_prompt or "")
        self.prompt = prompt
        completed_tools: set[str] = set()
        for i in range(self.max_iterations):
            pending_tools = sorted(set(self.search_agents) - completed_tools)
            selection_context = prompt + (
                "\n原始输入: "
                + str(requirement_prompt or "")
                + str(preference_prompt or "")
            )
            
            if pending_tools:
                selection_context += "\n待调用搜索工具: " + "、".join(pending_tools)
            else:
                selection_context += (
                    "\n所有搜索工具已完成。"
                    "本轮 action.name 必须是 finish；禁止继续调用搜索工具。"
                )
            selection_prompt = build_selection_prompt(
                self.selection_prompt,
                selection_context,
                self._tool_description(),
            )
            response = self.llm.invoke([
                {"role": "user", "content": selection_prompt}
            ])
            selection = normalise_selection_response(response)
            think = selection["think"]
            raw_action = selection["action"]
            action = raw_action if isinstance(raw_action, dict) else {}
            action_name = self._action_name(raw_action)
            tool_response = self._tooluse(action)
            if action_name in self.search_agents and not (
                isinstance(tool_response, dict) and tool_response.get("error")
            ):
                completed_tools.add(action_name)
            observation = {
                "result": tool_response.get("result", tool_response),
                "action": raw_action,
                "passed": bool(tool_response.get("passed", False)),
            }

            prompt += "\nThink: " + prompt_value(think)
            prompt += "\nAction: " + prompt_value(raw_action)
            prompt += "\nObservation: " + prompt_value(observation)
            self.prompt = prompt
            self.model_reasons.append(think)

            if self.validate_agent.validate(observation):
                self.result = self._validated_result(observation)
                return self.result

        self.result = {
            "passed": False,
            "error": "规划达到最大循环次数，结果仍未通过验证",
        }
        return self.result

    def _tooluse(self, command: Any) -> Any:
        actions = SearchAgent.normalise_actions(command)
        if not actions:
            self.last_result = {"passed": False, "error": "未提供有效 Action"}
            return self.last_result
        result: Any = None
        for action in actions:
            name = action.get("name")
            if name == "finish":
                result = {"passed": True, "result": action.get("arguments", {})}
            elif name in self.search_agents:
                result = self.search_agents[name].tooluse([action])
            else:
                result = {"passed": False, "error": f"未注册搜索 Agent: {name}"}
        self.last_result = result
        return result

    @staticmethod
    def _action_name(action: Any) -> str:
        if isinstance(action, dict):
            return str(action.get("name") or "")
        actions = SearchAgent.normalise_actions(action)
        return str(actions[0].get("name") or "") if actions else ""

    def _tool_description(self) -> str:
        descriptions = [
            'finish[{"plan": "..."}]',
            'search_attraction[{"city": "...", "keywords": "..."}]',
            'search_weather[{"city": "..."}]',
            'search_hotel[{"city": "...", "keywords": "..."}]',
            'search_restaurant[{"city": "...", "keywords": "..."}]',
        ]
        return "、".join(descriptions)

    def _validated_result(self, observation: Any) -> Any:
        if self.last_result is not None:
            return self.last_result
        return observation


def plan(requirement_prompt: str, preference_prompt: str = "", **kwargs: Any) -> Any:
    planner = PlanAgent(**kwargs)
    result = planner.plan(requirement_prompt, preference_prompt)
    if isinstance(result, dict):
        response = dict(result)
        response["loop_prompt"] = planner.prompt
        return response
    return {"passed": True, "result": result, "loop_prompt": planner.prompt}
