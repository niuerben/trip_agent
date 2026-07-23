"""使用 Microsoft Edge 自动验证旅行规划流程。

运行前提：
    1. 前端运行在 http://localhost:5173
    2. 后端运行在 http://localhost:8000
    3. 已安装 Playwright 浏览器依赖：python -m playwright install

示例：
    python test/test_trip_planner.py
    python test/test_trip_planner.py --city 广州 --preferences 美食 自然风光
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date
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
            "然后重新运行：python test/test_trip_planner.py"
        ) from error
    raise


TEST_USERNAME = "admin"
TEST_PASSWORD = "admin123"


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
    date_inputs = page.locator('input[placeholder="选择日期"]')
    if date_inputs.count() != 2:
        raise AssertionError(f"期望找到 2 个日期输入框，实际找到 {date_inputs.count()} 个")

    date_inputs.nth(input_index).click()
    target_day = str(target_date.day)
    target_iso = target_date.isoformat()
    day_cell = page.locator(
        f'div.ant-picker-dropdown:visible td[title="{target_iso}"]'
    )
    if day_cell.count() == 0:
        day_cell = page.locator(
            "div.ant-picker-dropdown:visible td.ant-picker-cell-in-view"
        ).filter(
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
            f"无法在当前日期面板中唯一定位 {target_date.isoformat()}，"
            f"匹配数量: {match_count}"
        )
    visible_day_cell.click()


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

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=not headed)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
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

        submit_button = page.get_by_role("button", name=re.compile("开始规划我的旅行"))
        if submit_button.count() != 1:
            raise AssertionError("找不到唯一的旅行规划提交按钮")

        submit_button.click()
        try:
            page.wait_for_url(re.compile(r"/result\?conversation="), timeout=120_000)
        except PlaywrightTimeoutError as error:
            page.screenshot(path=str(screenshot_path), full_page=True)
            raise AssertionError(
                f"旅行规划未在 120 秒内跳转到结果页，当前 URL: {page.url}。"
                f"截图已保存到: {screenshot_path}"
            ) from error

        page.screenshot(path=str(screenshot_path), full_page=True)
        result_url = page.url
        browser.close()
        return result_url


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
    print(f"旅行规划测试通过: {result_url}")


if __name__ == "__main__":
    main()
