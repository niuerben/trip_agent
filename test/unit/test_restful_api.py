"""SearchAttraction 工具行为测试。"""

import requests
import time

class RestfulApiTest():
    def test_root(self) -> None:
        start = time.perf_counter()
        print(f'连接根路由开始')

        url = "http://localhost:8000/"
        payload = ""
        response = requests.get(url,params=payload)

        end = time.perf_counter()
        print(f'连接根路由完成，耗时{(end-start)*1000} ms')
        print(response.json())
        # return self.assertTrue(result["result"]["success"])

    def test_talk(self) -> None:
        start = time.perf_counter()
        print(f'连接 talk 路由开始')

        url = "http://localhost:8000/api/talk"
        payload = {"message": "你好"}
        response = requests.post(url, json=payload)

        end = time.perf_counter()
        print(f'连接 talk 路由完成，耗时{(end-start)*1000} ms')
        body = response.json()
        print(body)

    def test_trip_plan(self) -> None:
        start = time.perf_counter()
        print(f'连接 talk 路由开始')

        url = "http://localhost:8000/api/trip/plan"
        payload = {
            "city": "深圳",
            "start_date": "2026-09-10",
            "end_date": "2026-09-12",
            "travel_days": 3,
            "transportation": "地铁",
            "accommodation": "经济",
            "preferences": ["人文"],
            "free_text_input": "世界之窗"
        }
        response = requests.post(url, json=payload)

        end = time.perf_counter()
        print(f'连接 talk 路由完成，耗时{(end-start)*1000} ms')
        body = response.json()
        print(body)

if __name__ == "__main__":
    test = RestfulApiTest()
    test.test_trip_plan()

