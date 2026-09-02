"""带统一可观测日志的 MCPTool。"""

from __future__ import annotations

import itertools
import json
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hello_agents.tools import MCPTool

from ..config import get_settings


_CALL_SEQUENCE = itertools.count(1)
_LOG_LOCK = threading.Lock()
_BEIJING_TZ = ZoneInfo("Asia/Shanghai")
_AGENT_LOOP_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "agent_loop_context", default=None
)
# 仅脱敏真正的凭证字段；不能把 ``keywords`` 误判为 API key。
_SENSITIVE_KEY = re.compile(
    r"^(?:api_?key|access_?token|refresh_?token|token|password|secret|authorization)$",
    re.IGNORECASE,
)

_TOOL_PURPOSES = {
    "maps_text_search": "搜索景点、酒店、餐厅等 POI",
    "maps_weather": "查询目标地区实时天气/预报",
    "maps_direction_walking_by_address": "查询步行路线",
    "maps_direction_driving_by_address": "查询驾车路线",
    "maps_direction_transit_integrated_by_address": "查询公共交通路线",
    "maps_geo": "将地址解析为高德坐标",
    "maps_regeocode": "将高德坐标反查行政区和地址",
    "maps_search_detail": "按 POI ID 查询地点详情",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if _SENSITIVE_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _compact(value: Any, limit: int = 600) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else f"{text[:limit]}…"


def _log_path() -> Path | None:
    configured = (get_settings().mcp_log_path or "").strip()
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return path


def _append_file_log(payload: dict[str, Any]) -> None:
    """仅写入 JSONL 文件，避免 MCP 参数和结果淹没后端终端。"""
    path = _log_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception as error:
        print(f"[MCP][LOG_ERROR] 无法写入日志: {type(error).__name__}: {error}")


@contextmanager
def agent_tool_execution_context(run_id: str, iteration: int):
    """将 FunctionCallAgent 的循环轮次写入同一轮 MCP 调用日志。"""
    token = _AGENT_LOOP_CONTEXT.set({"agent_run_id": run_id, "iteration": iteration})
    try:
        yield
    finally:
        _AGENT_LOOP_CONTEXT.reset(token)


class LoggingMCPTool(MCPTool):
    """在不修改 HelloAgents 包的前提下记录每次真实 MCP 调用。"""

    def run(self, parameters: dict[str, Any]) -> str:
        call_id = next(_CALL_SEQUENCE)
        started = time.perf_counter()
        action = str(parameters.get("action") or "call_tool")
        tool_name = str(parameters.get("tool_name") or action or self.name)
        arguments = _redact(parameters.get("arguments") or {})

        try:
            result = super().run(parameters)
        except Exception as error:
            result = f"MCP 调用异常: {type(error).__name__}: {error}"

        result_text = str(result)
        lowered = result_text.lower()
        status = "error" if any(
            marker in lowered
            for marker in ("mcp 操作失败", "异步操作失败", "工具调用失败", "错误：", "error")
        ) else "success"
        payload = {
            "call_id": call_id,
            "timestamp": datetime.now(_BEIJING_TZ).isoformat(timespec="seconds"),
            "status": status,
            "action": action,
            "tool_name": tool_name,
            "purpose": _TOOL_PURPOSES.get(tool_name, "执行高德 MCP 工具"),
            "arguments": arguments,
            "arguments_summary": _compact(arguments),
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "result_length": len(result_text),
            "result_summary": _compact(result_text),
        }
        if loop_context := _AGENT_LOOP_CONTEXT.get():
            payload.update(loop_context)
        _append_file_log(payload)
        return result_text
