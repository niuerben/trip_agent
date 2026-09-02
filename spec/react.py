from hello_agents import ReActAgent, HelloAgentsLLM, SimpleAgent
from dotenv import load_dotenv
from tool import executive, judicial

load_dotenv()
llm = HelloAgentsLLM()

liar = ReActAgent(
    name="总统",
    llm=llm,
    system_prompt='你是赖清德总统。你的执政党民主进步党下辖行政院、司法院，你控制三立新闻。你还有一个党内智库。你需要借助这些机构解决一些问题。大模型知识没有的，你利用工具调用获取信息。',
)

liar.add_tool(executive())
liar.add_tool(judicial())
# xmq = SimpleAgent(
#     name="党内智库",
#     llm=llm,
#     system_prompt='你是民进党党内智库。你需要为赖清德总统提供建议。'
# )
# xmq.add_tool(executive())
# response=xmq._execute_tool_call("行政院", '{"action": "请提供台湾的最新经济数据。"}')  # 调用工具进行测试
# print(f'工具调用结果: {response}')

q = "柯文哲被关在哪？"
response = liar.run(q)
print(f'总统回答: {response}')