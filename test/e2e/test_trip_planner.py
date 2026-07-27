"""使用 Microsoft Edge 自动验证旅行规划流程。

运行前提：
    1. 前端运行在 http://localhost:5173
    2. 后端运行在 http://localhost:8000
    3. 已安装 Playwright 浏览器依赖：python -m playwright install

示例：
    python e2e/test_trip_planner.py
    python e2e/test_trip_planner.py --city 广州 --preferences 美食 自然风光
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

try:
    from playwright.sync_api import (
        Page,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ModuleNotFoundError as error:
    if error.name == "playwright":
        raise SystemExit(
            "缺少 Playwright 依赖。请在当前运行脚本的 Python 环境中执行：\n"
            "  python -m pip install playwright\n"
            "  python -m playwright install\n"
            "然后重新运行：python e2e/test_trip_planner.py"
        ) from error
    raise


TEST_USERNAME = "admin1"
TEST_PASSWORD = "admin123"
TEST_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = TEST_ROOT.parent
BACKEND_LOG_ROOT = PROJECT_ROOT / "backend" / "logs"
TEST_LOG_PATH = TEST_ROOT / "logs" / "trip_planner_test.log"
AGENT_LOOP_LOG_PATH = BACKEND_LOG_ROOT / "agent_loop.log"
MCP_CALLS_LOG_PATH = BACKEND_LOG_ROOT / "mcp_calls.log"
PROMPT_AUDIT_LOG_PATH = TEST_ROOT / "logs" / "react_prompts.log"


def _write_generation_log(record: dict) -> None:
    """将一次旅行计划测试结果以 JSONL 追加到项目 logs 目录。"""
    TEST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TEST_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass
class TripTestCase:
    """可修改的旅行规划测试参数。"""

    city: str = "化州"
    start_date: date = date(2026, 7, 27)
    end_date: date = date(2026, 7, 29)
    preferences: tuple[str, ...] = ("美食",)
    transportation: str = "公共交通"
    accommodation: str = "经济型酒店"
    free_text_input: str = "三人行，吃好吃的，玩好玩的"


def _select_date(page: Page, target_date: date, input_index: int) -> None:
    """打开第 input_index 个日期选择器并选择日期。"""
    field_name = "开始日期" if input_index == 0 else "结束日期"
    date_inputs = page.locator('input[placeholder="选择日期"]')
    if date_inputs.count() != 2:
        raise AssertionError(f"期望找到 2 个日期输入框，实际找到 {date_inputs.count()} 个")

    date_input = date_inputs.nth(input_index)
    date_input.wait_for(state="visible", timeout=10_000)
    date_input.click(timeout=10_000)
    dropdown = page.locator("div.ant-picker-dropdown:visible")
    dropdown.wait_for(state="visible", timeout=10_000)
    target_day = str(target_date.day)
    target_iso = target_date.isoformat()
    day_cell = dropdown.locator(f'td[title="{target_iso}"]')
    if day_cell.count() == 0:
        day_cell = dropdown.locator("td.ant-picker-cell-in-view").filter(
            has_text=re.compile(rf"^{re.escape(target_day)}$")
        )
    match_count = day_cell.count()
    visible_day_cell = None
    for index in range(match_count):
        candidate = day_cell.nth(index)
        if candidate.is_visible():
            visible_day_cell = candidate
            break

    if visible_day_cell is None:
        raise AssertionError(
            f"无法在{field_name}面板中定位 {target_date.isoformat()}，"
            f"匹配数量: {match_count}"
        )
    visible_day_cell.click(timeout=10_000)
    dropdown.wait_for(state="hidden", timeout=10_000)


def _log_file_position(path: Path) -> int:
    """返回日志文件当前末尾位置；文件尚未创建时从 0 开始。"""
    try:
        with path.open("r", encoding="utf-8") as stream:
            stream.seek(0, 2)
            return stream.tell()
    except FileNotFoundError:
        return 0


def _read_new_json_lines(path: Path, position: int) -> tuple[int, list[dict]]:
    """读取日志文件自 position 后完整写入的 JSONL 记录。"""
    records: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            stream.seek(position)
            while True:
                line = stream.readline()
                if not line:
                    break
                next_position = stream.tell()
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # 后端正在写入的半行留到下一次轮询。
                    break
                if isinstance(record, dict):
                    records.append(record)
                position = next_position
    except FileNotFoundError:
        pass
    return position, records


def _write_prompt_audit(record: dict) -> None:
    """将后端完整 ReAct 交互复制到 test/logs，避免手动筛选 JSONL。"""
    event = record.get("event")
    run_id = record.get("agent_run_id") or "unknown"
    iteration = record.get("iteration", "-")
    lines: list[str] = []

    if event == "run_start":
        lines = [
            "\n" + "=" * 100,
            f"Agent run: {run_id}",
            f"开始事件: {json.dumps(record, ensure_ascii=False)}",
            "=" * 100,
        ]
    elif record.get("prompt_full") is not None:
        lines = [
            "\n" + "-" * 100,
            f"第 {iteration} 轮 Prompt | agent_run_id={run_id}",
            "[完整 Prompt]",
            str(record.get("prompt_full") or ""),
            "[模型原始响应]",
            str(record.get("model_response_full") or ""),
            "[完整 Observation]",
            str(record.get("observation_full") or ""),
        ]
    elif record.get("observation_full") is not None:
        lines = [
            "\n" + "-" * 100,
            f"第 {iteration} 轮 Observation | agent_run_id={run_id}",
            "[完整 Observation]",
            str(record.get("observation_full") or ""),
        ]

    if not lines:
        return
    PROMPT_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROMPT_AUDIT_LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def _print_performance_record(record: dict, source: str) -> None:
    """把 Agent/工具耗时压缩成一行可读的测试终端输出。"""
    if source == "agent":
        _write_prompt_audit(record)

    if source == "agent" and record.get("event") == "react_step":
        duration = record.get("duration_ms")
        if duration is not None:
            agent_type = record.get("agent_type") or "react"
            iteration = record.get("iteration", "?")
            print(f"Agent[{agent_type}] 第{iteration}轮模型调用耗时 {duration} ms")
        return

    if source == "agent" and record.get("event") == "react_observation":
        duration = record.get("tool_duration_ms")
        tool_name = record.get("tool_name")
        if duration is not None and tool_name:
            iteration = record.get("iteration", "?")
            print(f"工具[{tool_name}] 第{iteration}轮耗时 {duration} ms")
        return

    if source == "agent" and record.get("event") in {"run_end", "run_error"}:
        duration = record.get("duration_ms")
        if duration is None:
            return
        agent_type = record.get("agent_type") or "planning"
        reason = (
            record.get("termination_reason")
            or record.get("error_type")
            or "unknown"
        )
        run_id = str(record.get("agent_run_id") or "")[:8]
        print(f"Agent[{agent_type}] run={run_id} 耗时 {duration} ms，结束={reason}")
        return

    if source == "mcp" and record.get("action") == "call_tool":
        tool_name = record.get("tool_name") or "unknown"
        duration = record.get("duration_ms", "未知")
        status = record.get("status") or "unknown"
        iteration = record.get("iteration")
        suffix = f"，iteration={iteration}" if iteration is not None else ""
        print(f"工具[{tool_name}] 耗时 {duration} ms，状态={status}{suffix}")


def _monitor_backend_performance(
    stop_event: threading.Event,
    positions: dict[Path, int],
) -> None:
    """实时显示本次测试新增的 Agent 和 MCP 工具耗时。"""
    while not stop_event.is_set():
        for path, source in (
            (AGENT_LOOP_LOG_PATH, "agent"),
            (MCP_CALLS_LOG_PATH, "mcp"),
        ):
            new_position, records = _read_new_json_lines(path, positions[path])
            positions[path] = new_position
            for record in records:
                _print_performance_record(record, source)
        stop_event.wait(0.2)

    # 停止前再读一次，避免最后一个工具/Agent 记录尚未打印。
    for path, source in (
        (AGENT_LOOP_LOG_PATH, "agent"),
        (MCP_CALLS_LOG_PATH, "mcp"),
    ):
        new_position, records = _read_new_json_lines(path, positions[path])
        positions[path] = new_position
        for record in records:
            _print_performance_record(record, source)


def _select_ant_option(page: Page, select_index: int, option: str) -> None:
    """选择 ant-design-vue 下拉框中的选项。"""
    selects = page.locator(".ant-select")
    if selects.count() < select_index + 1:
        raise AssertionError(f"页面中没有第 {select_index + 1} 个下拉框")

    selects.nth(select_index).click()
    option_locator = page.locator(".ant-select-item-option-content").filter(
        has_text=re.compile(re.escape(option))
    )
    if option_locator.count() != 1:
        raise AssertionError(
            f"无法唯一定位下拉选项 {option!r}，匹配数量: {option_locator.count()}"
        )
    option_locator.click()


def fill_trip_form(page: Page, case: TripTestCase) -> None:
    """填写旅行规划表单。"""
    page.get_by_placeholder("例如: 北京").fill(case.city)
    _select_date(page, case.start_date, input_index=0)
    _select_date(page, case.end_date, input_index=1)

    _select_ant_option(page, select_index=0, option=case.transportation)
    _select_ant_option(page, select_index=1, option=case.accommodation)

    for preference in case.preferences:
        checkbox = page.get_by_role("checkbox", name=re.compile(re.escape(preference)))
        if checkbox.count() != 1:
            raise AssertionError(f"找不到旅行偏好复选框: {preference}")
        checkbox.check()

    page.get_by_placeholder(
        "请输入您的额外要求,例如:想去看升旗、需要无障碍设施、对海鲜过敏等..."
    ).fill(case.free_text_input)


def login(page: Page, username: str, password: str) -> None:
    """登录测试账号，并确认页面已经进入用户态。"""
    if not username or not password:
        raise ValueError("登录测试需要同时提供 username 和 password")

    user_button = page.get_by_role("button", name="登录", exact=True)
    if user_button.count() == 0:
        raise AssertionError("找不到登录按钮")
    user_button.first.click()

    modal = page.locator(".ant-modal:visible")
    modal.get_by_placeholder("请输入用户名").fill(username)
    modal.get_by_placeholder("请输入密码").fill(password)
    submit_button = modal.locator('button[type="submit"]')
    if submit_button.count() != 1:
        raise AssertionError(
            f"登录弹窗中期望找到 1 个提交按钮，实际找到 {submit_button.count()} 个"
        )
    submit_button.click()

    page.get_by_role("button", name=re.compile(rf"^{re.escape(username)}\s*[·|]")).wait_for(
        state="visible",
        timeout=10_000,
    )


def run_trip_planner_test(
    case: TripTestCase | None = None,
    base_url: str = "http://localhost:5173",
    headed: bool = True,
) -> str:
    """在 Edge 中执行旅行规划测试并返回结果页 URL。"""
    case = case or TripTestCase()
    screenshot_path = Path(__file__).with_name("trip-planner-result.png")
    started_at = datetime.now().astimezone()
    started_monotonic = time.perf_counter()
    result_url = None
    status = "failed"
    error_message = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=not headed)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            try:
                try:
                    page.goto(base_url, wait_until="domcontentloaded")
                except Exception as error:  # noqa: BLE001 - 转换为可执行的测试提示
                    if "ERR_CONNECTION_REFUSED" in str(error):
                        raise AssertionError(
                            f"无法连接前端 {base_url}。请先在另一个终端启动前端：\n"
                            "  cd frontend\n"
                            "  npm run dev -- --host 0.0.0.0\n"
                            "后端也需运行在 http://localhost:8000。"
                        ) from error
                    raise
                page.get_by_role("main").wait_for()

                login(page, TEST_USERNAME, TEST_PASSWORD)
                fill_trip_form(page, case)

                submit_button = page.get_by_role(
                    "button", name=re.compile("开始规划我的旅行")
                )
                if submit_button.count() != 1:
                    raise AssertionError("找不到唯一的旅行规划提交按钮")

                log_positions = {
                    AGENT_LOOP_LOG_PATH: _log_file_position(AGENT_LOOP_LOG_PATH),
                    MCP_CALLS_LOG_PATH: _log_file_position(MCP_CALLS_LOG_PATH),
                }
                performance_stop = threading.Event()
                performance_monitor = threading.Thread(
                    target=_monitor_backend_performance,
                    args=(performance_stop, log_positions),
                    name="trip-planner-performance-monitor",
                    daemon=True,
                )
                performance_monitor.start()

                api_error: dict[str, str] = {}

                def capture_plan_error(response) -> None:
                    if (
                        response.request.method == "POST"
                        and "/api/trip/plan" in response.url
                        and response.status >= 400
                    ):
                        try:
                            api_error["detail"] = response.text()
                        except Exception:  # noqa: BLE001 - 保留状态码即可
                            api_error["detail"] = "无法读取接口响应体"
                        api_error["status"] = str(response.status)

                page.on("response", capture_plan_error)
                submit_button.click()
                try:
                    deadline = time.perf_counter() + 60
                    while not re.search(r"/result\?conversation=", page.url):
                        if api_error:
                            raise AssertionError(
                                "旅行规划接口失败，"
                                f"HTTP {api_error.get('status', '未知')}："
                                f"{api_error.get('detail', '无响应详情')}"
                            )
                        if time.perf_counter() >= deadline:
                            raise PlaywrightTimeoutError(
                                "旅行规划超过 60 秒仍未跳转到结果页"
                            )
                        page.wait_for_timeout(200)
                except PlaywrightTimeoutError as error:
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    raise AssertionError(
                        f"旅行规划未在 60 秒内跳转到结果页，当前 URL: {page.url}。"
                        f"截图已保存到: {screenshot_path}"
                    ) from error

                page.screenshot(path=str(screenshot_path), full_page=True)
                result_url = page.url
                status = "success"
                return result_url
            finally:
                if "performance_stop" in locals():
                    performance_stop.set()
                    performance_monitor.join(timeout=2)
                browser.close()
    except Exception as error:  # noqa: BLE001 - 先记录，再保留原始失败堆栈
        error_message = f"{type(error).__name__}: {error}"
        raise
    finally:
        finished_at = datetime.now().astimezone()
        duration_seconds = round(time.perf_counter() - started_monotonic, 3)
        _write_generation_log({
            "event": "trip_planner_test_completed",
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "duration_seconds": duration_seconds,
            "duration_ms": round(duration_seconds * 1000),
            "status": status,
            "base_url": base_url,
            "headed": headed,
            "city": case.city,
            "start_date": case.start_date.isoformat(),
            "end_date": case.end_date.isoformat(),
            "preferences": list(case.preferences),
            "transportation": case.transportation,
            "accommodation": case.accommodation,
            "result_url": result_url,
            "screenshot_path": str(screenshot_path),
            "error": error_message,
        })
        print(
            f"旅行规划测试{'完成' if status == 'success' else '失败'}，"
            f"耗时 {duration_seconds:.3f} 秒"
        )
        print(f"ReAct完整Prompt审计日志: {PROMPT_AUDIT_LOG_PATH}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用 Microsoft Edge 测试旅行规划")
    parser.add_argument("--city", default="深圳坪山")
    parser.add_argument("--start-date", default="2026-07-27")
    parser.add_argument("--end-date", default="2026-07-29")
    parser.add_argument("--preferences", nargs="+", default=["美食","休闲"])
    parser.add_argument("--transportation", default="公共交通")
    parser.add_argument("--accommodation", default="经济型酒店")
    parser.add_argument("--free-text", default="三人行，吃好吃的，玩好玩的，每餐预算人均不超过 40 元")
    parser.add_argument("--base-url", default="http://localhost:5173")
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    print(f"【端到端测试】test_trip_planner | 前端={args.base_url}")
    print("说明：在浏览器中验证登录、规划提交和结果页跳转。")
    case = TripTestCase(
        city=args.city,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        preferences=tuple(args.preferences),
        transportation=args.transportation,
        accommodation=args.accommodation,
        free_text_input=args.free_text,
    )
    result_url = run_trip_planner_test(
        case=case,
        base_url=args.base_url,
        headed=not args.headless,
    )
    print(f"通过：已跳转至结果页 | {result_url}")


if __name__ == "__main__":
    main()
