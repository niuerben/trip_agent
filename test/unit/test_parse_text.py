"""SearchAttraction 工具行为测试。"""

import time
import sys
from pathlib import Path

from hello_agents import ReActAgent
# __file__ 表示当前路径的字符串
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from backend.app.services.llm_service import get_llm

class ParseTextTest():
    def test_parse_output(self) -> None:
        start = time.perf_counter()
        print(f'解析输出开始')
        response_text = 'Thought: 用户需要陆丰三日游攻略。我已获取景点和天气信息。天气显示未来几天有中雨到大雨，需推荐适合雨天的景点并给出实用建议。信息充分，可以直接总结行程。\nAction: Finish[根据搜索，陆丰近期天气以中雨/大雨为主（30℃左右），建议携带雨具并优先安排可避雨的景点与室内活动。推荐三日游行程如下：\n\n**Day 1：玄武山旅游区（碣石镇）**  \n- 上午：游览玄武山旅游区，含元山寺、福星塔等，是陆丰最核心的祈福文化景区，建筑可避雨。  \n- 下午：附近可逛石洲文化公园或清凉寺，傍晚返回市区品尝陆丰特色美食（如咸茶、薄饼）。\n\n**Day 2：清峰禅寺 → 玉照公园 → 妈祖文化园**  \n- 上午：前往清峰禅寺（清云山）感受禅意，寺庙殿堂可避雨。  \n- 下午：到玉照公园散步，之后去金厢镇妈祖文化园（若雨势大则改为待渡山或甲子公园）。  \n- 傍晚：在东海街道或金厢镇吃海鲜、蚝烙。\n\n**Day 3：银潭飞瀑 / 陂洋半月湾 → 水月宫或峰山禅寺**  \n- 上午：若雨势较小，可去银潭飞瀑或陂洋半月湾看雨中的山水瀑布；若雨大，建议改去定光禅寺或佛光寺参访。  \n- 下午：顺路到观音岭水月宫眺望海景，或在市区购买特产（如南塘花生糖、甲子鱼丸）。  \n- 返程前可到南坑村练氏祖祠或奎湖古堡（如天气允许）。\n\n**出行提示**  \n- 山区景点（银潭飞瀑、半月湾）雨天路滑，注意安全。  \n- 所有寺庙景点均有避雨空间，适合雨天参观。  \n- 餐饮推荐：陆丰咸茶、虾饼、薄饼、海鲜。  \n- 住宿：建议选东海镇或碣石镇中心酒店，方便出行。]'
        llm = get_llm()
        react_agent = ReActAgent("解析器",llm)
        thought, action = react_agent._parse_output(response_text)
        
        end = time.perf_counter()
        print(f'解析输出完成，耗时{(end-start)*1000} ms')
        print(thought)
        print(action)
        # return self.assertTrue(result["result"]["success"])

    def test_parse_action_input(self) -> None:
        start = time.perf_counter()
        print(f'解析输入开始')
        action = ''
        llm = get_llm()
        react_agent = ReActAgent("解析器",llm)
        final_answer = react_agent._parse_action_input(action)
        
        end = time.perf_counter()
        print(f'解析输入完成，耗时{(end-start)*1000} ms')
        print(final_answer)


if __name__ == "__main__":
    test = ParseTextTest()
    test.test_parse_output()
    test.test_parse_action_input
