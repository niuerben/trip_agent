"""PlanAgent 运行集成测试。"""

import time
import sys
from pathlib import Path

# __file__ 表示当前路径的字符串
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from backend.app.agents.talk_agent import TalkAgent
from backend.app.models.schemas import TalkRequest

class PlanAgentTest():
    def test_run_plan_agent(self) -> None:
        start = time.perf_counter()
        print(f'talk agent 运行开始')

        plan_agent = TalkAgent()
        request = TalkRequest(
            conversation_id="1",
            city="北京",
            plan_context="三天两夜",
            messages=[],
            message="我想去北京旅游，帮我规划一个三天两夜的行程。",
        )
        response = plan_agent.talk(request)
        end = time.perf_counter()
        print(f'talk agent 运行完成，耗时{(end-start)*1000} ms')
        print(response)
        # return self.assertTrue(result["result"]["success"])
    

if __name__ == "__main__":
    test = PlanAgentTest()
    test.test_run_plan_agent()
