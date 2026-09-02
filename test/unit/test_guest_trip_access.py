"""验证未登录 guest 无法访问旅行规划接口。

需要先启动后端：
    python backend/run.py

运行：
    python test/unit/test_guest_trip_access.py
"""

from __future__ import annotations

import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json


BASE_URL = "http://localhost:8000"
TRIP_PAYLOAD = json.dumps({
    "city": "深圳",
    "start_date": "2026-09-05",
    "end_date": "2026-09-07",
    "travel_days": 3,
    "transportation": "公共交通",
    "accommodation": "经济型酒店",
    "preferences": [],
    "free_text_input": "",
}).encode("utf-8")


class GuestTripAccessTest(unittest.TestCase):
    def request_as_guest(self, authorization: str | None = None):
        headers = {"Content-Type": "application/json"}
        if authorization is not None:
            headers["Authorization"] = authorization
        request = Request(
            f"{BASE_URL}/api/trip/plan",
            data=TRIP_PAYLOAD,
            headers=headers,
            method="POST",
        )
        try:
            return urlopen(request, timeout=10)
        except HTTPError as error:
            return error
        except (TimeoutError, URLError) as error:  # 后端未启动或无法连接
            return error

    def assert_guest_rejected(self, authorization: str | None) -> None:
        response = self.request_as_guest(authorization)
        if isinstance(response, URLError) and not hasattr(response, "code"):
            self.skipTest(f"后端未启动：{response}")
        self.assertEqual(
            getattr(response, "code", None),
            401,
            f"guest 请求未被拒绝，响应={response}",
        )

    def test_request_without_authorization_is_rejected(self) -> None:
        self.assert_guest_rejected(None)

    def test_local_guest_bearer_is_rejected(self) -> None:
        self.assert_guest_rejected("Bearer local:guest")


if __name__ == "__main__":
    unittest.main()
