"""PlanAgent 运行集成测试。"""

import time
import sys
from pathlib import Path
# __file__ 表示当前路径的字符串
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from backend.app.agents.plan_agent import PlanAgent

class PlanAgentTest():
    def test_run_plan_agent(self) -> None:
        start = time.perf_counter()
        print(f'plan agent 运行开始')

        plan_agent = PlanAgent()
        response = plan_agent.run("陆丰旅游三日游")
        end = time.perf_counter()
        print(f'plan agent 运行完成，耗时{(end-start)*1000} ms')
        print(response)
        # return self.assertTrue(result["result"]["success"])
    

if __name__ == "__main__":
    test = PlanAgentTest()
    test.test_run_plan_agent()
