"""SearchAttraction 工具行为测试。"""

import time
import sys
from pathlib import Path
# __file__ 表示当前路径的字符串
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from backend.app.agents.tool_lib import SearchAttraction, SearchHotel, SearchRestaurant,SearchWeather

class SearchToolTest():
    def test_run_searches_attraction(self) -> None:
        start = time.perf_counter()
        print(f'景点搜索开始')
        tool_search_attraction = SearchAttraction()

        result = tool_search_attraction.run({"input": "广州塔,广州"})
        end = time.perf_counter()
        print(f'景点搜索完成，耗时{(end-start)*1000} ms')
        print(result)
        # return self.assertTrue(result["result"]["success"])
    
    def test_run_searches_weather(self) -> None:
        start = time.perf_counter()
        print(f'天气搜索开始')
        tool_search_weather = SearchWeather()

        result = tool_search_weather.run({"input": "陆丰"})
        end = time.perf_counter()
        print(f'天气搜索完成，耗时{(end-start)*1000} ms')
        print(result)

    def test_run_searches_hotel(self) -> None:
        start = time.perf_counter()
        print(f'酒店搜索开始')
        tool_search_hotel = SearchHotel()

        result = tool_search_hotel.run({"input": "情侣,陆丰"})
        end = time.perf_counter()
        print(f'酒店搜索完成，耗时{(end-start)*1000} ms')
        print(result)

    def test_run_searches_restaurant(self) -> None:
        start = time.perf_counter()
        print(f'餐馆搜索开始')
        tool_search_restaurant = SearchRestaurant()

        result = tool_search_restaurant.run({"input": "港式,陆丰"})
        end = time.perf_counter()
        print(f'餐馆搜索完成，耗时{(end-start)*1000} ms')
        print(result)

if __name__ == "__main__":
    test = SearchToolTest()
    # test.test_run_searches_attraction()
    # test.test_run_searches_weather()
    # test.test_run_searches_hotel()
    test.test_run_searches_restaurant()
