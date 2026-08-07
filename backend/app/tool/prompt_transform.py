"""Format conversions at the boundary between agents and the LLM."""

from __future__ import annotations

import json
import re
from typing import Any

from ..agents.search_agent import SearchAgent


def prompt_value(value: Any) -> str:
    """Convert an observation, thought, or action to prompt text."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def build_react_instruction(
    prompt: str,
    preference_prompt: str,
    observation: Any,
    tool_description: str,
    system_prompt: str = "",
) -> str:
    """Build the single user message sent to the backend LLM."""
    return (
        f"系统提示词:\n{system_prompt}\n"
        f"需求: {prompt}\n偏好: {preference_prompt}\n"
        f"观察: {prompt_value(observation)}\n可用工具: {tool_description}\n"
        "请按格式返回：\nThink: 思考内容\nAction: 工具名[JSON参数]"
    )


def build_selection_prompt(
    selection_prompt: str,
    prompt: str,
    tool_description: str,
) -> str:
    """Build the structured selection request sent to the backend LLM."""
    return (
        f"{selection_prompt}\n\n"
        f"可用工具：{tool_description}\n\n"
        f"当前规划上下文：\n{prompt}"
    )


def normalise_selection_response(response: Any) -> dict[str, Any]:
    """Normalize backend LLM output to the PlanAgent selection schema."""
    if isinstance(response, dict):
        if "content" in response and "action" not in response:
            return normalise_selection_response(response["content"])
        return {
            "think": response.get("think") or response.get("reason") or "",
            "action": response.get("action"),
        }
    if not isinstance(response, str):
        return {"think": "", "action": None}

    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, (dict, str)):
            return normalise_selection_response(payload)
    except json.JSONDecodeError:
        pass
    try:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            payload = json.loads(text[start:end + 1])
            if isinstance(payload, dict):
                return normalise_selection_response(payload)
            if isinstance(payload, str):
                return normalise_selection_response(payload)
    except json.JSONDecodeError:
        pass

    reason, actions = normalise_model_response(text, [])
    return {"think": reason, "action": actions}


def normalise_model_response(response: Any, action: list[Any]) -> tuple[Any, list[Any]]:
    """Convert model output into a reason and a normalized action list."""
    if isinstance(response, tuple) and len(response) == 2:
        reason, returned_action = response
        return reason, returned_action if isinstance(returned_action, list) else [returned_action]
    if action:
        return response, action
    if not isinstance(response, str):
        return response, []
    text = response.strip()
    match = re.search(
        r"(?is)(?:^|\n)\s*(?:\*\*)?Action\s*[:：]\s*([A-Za-z_]\w*)\[(.*)\]\s*$",
        text,
    )
    if not match:
        return text, []
    parsed_action = SearchAgent.normalise_actions(
        f"{match.group(1)}[{match.group(2)}]"
    )
    reason = re.sub(
        r"^\s*(?:Thought|Think)\s*[:：]\s*",
        "",
        text[:match.start()].strip(),
        flags=re.IGNORECASE,
    )
    return reason, parsed_action
