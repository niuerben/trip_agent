"""记录 FunctionCallAgent 的模型决策与工具循环。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..config import get_settings


_LOG_LOCK = threading.Lock()
_BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _loop_log_path() -> Path:
    path = Path(get_settings().agent_loop_log_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return path


def _summary(value: str, limit: int = 300) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit]}…"


def log_agent_loop(event: str, run_id: str, **fields: Any) -> None:
    """以 JSONL 写入一次规划 Agent 运行中的循环事件。"""
    payload = {
        "timestamp": datetime.now(_BEIJING_TZ).isoformat(timespec="seconds"),
        "event": event,
        "agent_run_id": run_id,
        **fields,
    }
    path = _loop_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception as error:
        print(f"Agent 循环日志写入失败: {type(error).__name__}: {error}")
