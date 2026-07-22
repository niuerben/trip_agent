"""项目 API 连通性检查。

运行：
    backend\\venv\\Scripts\\python.exe test\\test_api.py
    backend\\venv\\Scripts\\python.exe test\\test_api.py --skip-trip

脚本只打印状态、耗时和错误摘要，不打印任何 API Key、JWT 或数据库密码。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
load_dotenv(BACKEND_DIR / ".env")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    elapsed_ms: int


def run_check(name: str, callback) -> CheckResult:
    started = time.perf_counter()
    try:
        detail = callback()
        return CheckResult(name, True, str(detail), int((time.perf_counter() - started) * 1000))
    except Exception as error:  # noqa: BLE001 - 测试脚本需要继续执行后续检查
        return CheckResult(name, False, f"{type(error).__name__}: {error}", int((time.perf_counter() - started) * 1000))


def request_json(method: str, url: str, **kwargs) -> tuple[requests.Response, Any]:
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 20), **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = response.text[:300]
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {payload}")
    return response, payload


def check_health(base_url: str) -> str:
    _, payload = request_json("GET", f"{base_url}/health")
    if payload.get("status") != "healthy":
        raise RuntimeError(f"服务状态异常: {payload}")
    return f"backend=healthy, database={payload.get('database', 'unknown')}"


def check_login(base_url: str) -> str:
    username = os.getenv("AUTH_USERNAME", "admin")
    password = os.getenv("AUTH_PASSWORD", "admin123")
    _, payload = request_json(
        "POST",
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
    )
    if not payload.get("access_token"):
        raise RuntimeError("登录响应缺少 access_token")
    return "JWT login=ok"


def check_conversations(base_url: str) -> str:
    username = os.getenv("AUTH_USERNAME", "admin")
    password = os.getenv("AUTH_PASSWORD", "admin123")
    _, login = request_json(
        "POST",
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
    )
    _, payload = request_json(
        "GET",
        f"{base_url}/api/conversations",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    if not isinstance(payload, list):
        raise RuntimeError("聊天记录接口返回格式不是数组")
    return f"conversations={len(payload)}"


def check_trip_plan(base_url: str) -> str:
    request_data = {
        "city": "化州",
        "start_date": "2026-07-27",
        "end_date": "2026-07-29",
        "travel_days": 3,
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
        "preferences": ["美食"],
        "free_text_input": "三人行，吃好吃的，玩好玩的",
    }
    _, payload = request_json(
        "POST",
        f"{base_url}/api/trip/plan",
        json=request_data,
        timeout=130,
    )
    if payload.get("success") is not True or not payload.get("data"):
        raise RuntimeError(f"旅行规划响应异常: {payload}")
    plan = payload["data"]
    suggestion = plan.get("overall_suggestions", "")
    if "基础行程" in suggestion or "超时/不可用" in suggestion:
        raise RuntimeError(f"旅行规划发生降级: {suggestion[:100]}")
    return f"trip_plan=ok, days={len(plan.get('days', []))}, full_model_plan=yes"


def check_amap() -> str:
    api_key = os.getenv("AMAP_API_KEY") or os.getenv("AMAP_MAPS_API_KEY")
    if not api_key:
        raise RuntimeError("AMAP_API_KEY/AMAP_MAPS_API_KEY 未配置")
    response, payload = request_json(
        "GET",
        "https://restapi.amap.com/v3/place/text",
        params={"key": api_key, "keywords": "景点", "city": "化州", "citylimit": "true", "extensions": "all"},
        timeout=15,
    )
    if str(payload.get("status")) != "1":
        raise RuntimeError(f"高德返回异常: {payload.get('info')} ({payload.get('infocode')})")
    return f"amap=ok, pois={len(payload.get('pois') or [])}, http={response.status_code}"


def check_llm() -> str:
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = (os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "").rstrip("/")
    model = os.getenv("LLM_MODEL_ID") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    if not api_key or not base_url:
        raise RuntimeError("LLM_API_KEY/OPENAI_API_KEY 或服务地址未配置")

    _, payload = request_json(
        "POST",
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": "只回复 OK"}],
            "temperature": 0,
            "max_tokens": 8,
        },
        timeout=30,
    )
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM响应缺少 choices: {payload}")
    return f"llm=ok, model={model}"


async def check_postgres_async() -> str:
    import asyncpg

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 未配置")
    asyncpg_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(asyncpg_url)
    try:
        rows = await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        tables = sorted(row["tablename"] for row in rows)
        required = {"app_users", "conversations"}
        missing = required.difference(tables)
        if missing:
            raise RuntimeError(f"缺少数据表: {sorted(missing)}")
        return f"postgres=ok, tables={','.join(tables)}"
    finally:
        await connection.close()


def check_postgres() -> str:
    return asyncio.run(check_postgres_async())


def main() -> int:
    parser = argparse.ArgumentParser(description="检查旅行规划项目各 API 是否可用")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--skip-trip", action="store_true", help="跳过会实际调用模型/高德的旅行规划接口")
    args = parser.parse_args()

    checks = [
        ("health", lambda: check_health(args.base_url)),
        ("auth.login", lambda: check_login(args.base_url)),
        ("conversations", lambda: check_conversations(args.base_url)),
        ("postgres", check_postgres),
        ("amap.rest", check_amap),
        ("llm.chat", check_llm),
    ]
    if not args.skip_trip:
        checks.append(("trip.plan", lambda: check_trip_plan(args.base_url)))

    results = [run_check(name, callback) for name, callback in checks]
    print("API 检查结果")
    print("=" * 72)
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status:4}] {result.name:<18} {result.elapsed_ms:>6} ms  {result.detail}")
    print("=" * 72)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
