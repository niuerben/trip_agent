# 配置好同级文件夹下.env中的大模型API, 可参考code文件夹配套的.env.example，也可以拿前几章的案例的.env文件复用。
from hello_agents import SimpleAgent, HelloAgentsLLM
from dotenv import load_dotenv
from hello_agents.tools import ToolParameter


from tool import prc2roc_year_calculator

# 加载环境变量
load_dotenv()

# 创建LLM实例 - 框架自动检测provider
llm = HelloAgentsLLM()

# 或手动指定provider（可选）
# llm = HelloAgentsLLM(provider="modelscope")

# 创建SimpleAgent
agent = SimpleAgent(
    name="陆委会发言人",
    llm=llm,
    system_prompt="你是陆委会发言人，不是 AI 模型，请用繁体中文回答。你需要在众多记者问题中选一个回答。当你没法回答时，请直接说“我无法回答”。",
)

TVBS_reporter = SimpleAgent(
    name="TVBS 记者",
    llm=llm,
    system_prompt="你是 TVBS 记者，不是 AI 模型，请用繁体中文回答。你的任务是用 TVBS 的立场向发言人提问。当对方的回答已经包含了你想要的答案时，并且追问必要时，请返回“问题已解答”。",
)

SANLI_reporter = SimpleAgent(
    name="三立新闻记者",
    llm=llm,
    system_prompt="你是三立新闻记者，不是 AI 模型，请用繁体中文回答。你的任务是用三立新闻的立场向发言人提问。当对方的回答已经包含了你想要的答案时，并且追问必要时，请返回“问题已解答”。",
)


agent.add_tool(prc2roc_year_calculator())  # 添加公历转民国年计算器工具
print("=" * 20)
print(f'已添加的工具: {agent.list_tools()}')  # 查看已添加的工具
response = agent._execute_tool_call(
    "公历纪年转民国纪年计算器",
    '{"year": 2026}',
)  # 调用工具进行测试
print(f'工具调用结果: {response}')

exit(0)

# 基础对话
init_prompt = "你需要采访陆委会发言人，请准确返回1个问题。"
for _ in range(10):  # 进行10轮对话
    q1 = TVBS_reporter.run(init_prompt)
    print("TVBS 记者：" + q1)
    print("="*20)

    if "问题已解答" in q1:
        print("采访结束，记者的问题已解答。")
        break

    SANLI_q1 = SANLI_reporter.run(init_prompt)
    print("三立新闻记者：" + SANLI_q1)
    print("="*20)

    from hello_agents.core.message import Message
    agent.add_message(Message(content=q1, role="user"))
    agent.add_message(Message(content=SANLI_q1, role="user"))
    a1 = agent.run("TVBS 提问：" + q1 + "\n三立新闻提问：" + SANLI_q1)
    print("陆委会发言人：" + a1)
    print("="*20)

    init_prompt = a1  # 将发言人的回答作为下一轮记者的提问
    if "我无法回答" in a1:
        print("采访结束，发言人无法回答问题。")
        break

print("="*20)
print(agent.get_history())  # 查看对话历史

# 添加工具功能（可选）
from hello_agents.tools import CalculatorTool
calculator = CalculatorTool()
# 需要实现7.4.1的MySimpleAgent进行调用，后续章节会支持此类调用方式
# agent.add_tool(calculator)

# 现在可以使用工具了
# response = agent.run("请帮我计算 2 + 3 * 4")
# print(response)

# 查看对话历史
# print(f"历史消息数: {len(agent.get_history())}")
