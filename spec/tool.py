from pathlib import Path

from dotenv import load_dotenv
from hello_agents import HelloAgentsLLM
from hello_agents.tools import Tool, ToolParameter

load_dotenv()


class prc2roc_year_calculator(Tool):
    def __init__(self):
        super().__init__(
            name="公历纪年转民国纪年计算器",
            description="将公历年份转换为民国年份",
            expandable=False,
        )

    def run(self, parameters: dict) -> str:
        year_value = parameters.get("year")
        if not isinstance(year_value, int):
            return "错误：year 必须是整数，例如 2024。"

        if year_value >= 1912:
            return f"民国{year_value - 1911}年，调用了prc2roc_year_calculator工具。"
        else:
            return "公历年份小于1912，无法转换为民国年份。"

    def get_parameters(self) -> list:
        return [
            ToolParameter(
                name="year",
                type="int",
                description="公历年份",
                required=True
            )
        ]

class executive(Tool):
    def __init__(self):
        super().__init__(
            name="行政院",
            description="台湾行政院。现由民进党控制，负责管理台湾的行政事务。",
            expandable=False,
        )
        self.llm = HelloAgentsLLM()

    def run(self, parameters: dict) -> str:
        action = parameters.get("action")
        if not action:
            return "错误：未提供要执行的操作。"
        # 在这里可以添加实际的执行逻辑
        memory = "行政院长卓荣泰下周访问日本"

        response = self.llm.invoke(messages=[
            {"role": "user", "content": f"你是台湾行政院负责人。你的记忆: {memory}。\n总统赖清德要求你执行以下操作: {action}。\n请根据行政院的记忆返回信息。记忆里没有只返回'我不知道'四个字，不能再多。"}
        ])

        return response

    def get_parameters(self) -> list:
        return [
            ToolParameter(
                name="action",
                type="string",
                description="要执行的操作",
                required=True
            )
        ]

class judicial(Tool):
    def __init__(self):
        super().__init__(
            name="司法院",
            description="台湾司法院。现由民进党控制，负责管理台湾的司法事务。",
            expandable=False,
        )
        self.llm = HelloAgentsLLM()
 
    def run(self, parameters: dict) -> str:
        action = parameters.get("action")
        if not action:
            return "错误：未提供要执行的操作。"
        # 在这里可以添加实际的执行逻辑
        memory = "柯文哲被关押在土城看守所"

        response = self.llm.invoke(messages=[
            {"role": "user", "content": f"你是台湾司法院负责人。你的记忆: {memory}。\n总统赖清德要求你执行以下操作: {action}。\n请根据司法院的记忆返回信息。记忆里没有只返回'我不知道'四个字，不能再多。"}
        ])

        return response

    def get_parameters(self) -> list:
        return [
            ToolParameter(
                name="action",
                type="string",
                description="要执行的操作",
                required=True
            )
        ]