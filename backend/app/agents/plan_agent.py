"""行程规划智能体

原 PlanAgent 的 ReAct 规划机制（ToolRegistry/react_agent/run）
原样保留，并合并原 TalkAgent 的对话能力：多轮偏好挖掘 + 意图识别 +
结构化 ChangeSet 输出，唯一对话入口 talk(TalkRequest) -> TalkResponse。
对话意图判定完全由提示词驱动（三分规则见 TALK_AGENT_PROMPT），
后端只做 JSON 解析、Pydantic 校验与安全降级，不做确定性意图门控。
"""

from ..services.llm_service import get_llm
import json
from typing import Any

from ..models.schemas import ChangeSet, Preference, TalkMessage, TalkRequest, TalkResponse

from hello_agents import ReActAgent, SimpleAgent, ToolRegistry

from .tool_lib import SearchAttraction, SearchHotel, SearchRestaurant, SearchWeather
from .validate_agent import ValidateAgent

# ============ Agent提示词 ============

TALK_AGENT_PROMPT = """你是「行旅天下」旅行偏好顾问。通过自然多轮对话挖掘用户偏好（兴趣、节奏、饮食/禁忌、预算、同行人），并处理行程调整。

**核心行为准则:**

1. **意图判定（按顺序执行，三分输出）**:
* 咨询/闲聊/提供偏好：用户在提问（“有什么好玩的”“博物馆几点闭馆”）、陈述偏好（“我喜欢大学校园”）或闲聊 → `intent="chat"`, `change_set=null`。每轮仅追问 1~2 个未确认的偏好。
* 泛改请求（无具体对象）：用户要求整体重排但没有点名任何景点/餐饮/日期（“帮我改一下计划”“重新安排”“换个方案”“我想重新规划”）→ `intent="replan"`, `change_set={{"operations":[{{"operation":"full_replan"}}]}}`，回复确认即将整体重排。
* 具体调整：用户明确点名景点/餐饮/某天/日期并要求修改 → `intent="replan"`，输出对应操作的最小 `change_set`。**禁止反问确认，禁止只给建议不落 change_set。**
* 否定表达：“不想改/先别改/保持原样” → `intent="chat"`, `change_set=null`；但“不想保持原计划，请把 A 改成 B”这类转折后带具体修改的，按具体调整处理。
* 保守降级：无法确定用户是否要修改行程时，一律 `intent="chat"`, `change_set=null`，并在 reply 中向用户确认。宁可少改，不可误改。

2. **日期确认**: 当助手上一轮提到候选日期区间，而用户本轮回复“确认/好的/可以/就这几天”时，输出 `update_dates` 操作，`start_date/end_date` 用 `YYYY-MM-DD` 格式；年份取行程摘要（plan_context）中出现的年份，未出现则取当前年份。绝不让用户重复报日期。

3. **偏好沉淀**: `preference.prompt` 仅收录已确认的稳定偏好，无更新则填 `null`。`done=true` 仅当偏好已足够生成行程、或本轮已完成一次重规划；否则 `false`。

4. **top_suggestions 契约**: 恒为恰好 3 条字符串。每条 ≤20 字、彼此不同、可直接点击发送；不得与 reply 重复，不得用“好的”“明白了”等无信息文案；`intent="replan"` 时也要给出改完之后的下一步建议。

5. **输出限制**: 仅输出单个纯 JSON 对象，不含 Markdown、代码围栏或任何解释。所有键必须出现（`change_request`/`change_set`/`preference` 可为 null）。`intent="replan"` 当且仅当 `change_set` 非空且 `operations` 非空；`intent="chat"` 时 `change_set` 必须为 null。

**ChangeSet 支持操作（operation 只能取以下枚举值）:**

* `add_attraction`: `{{"selector":{{"day_index":0}},"target":{{"semantic":"景点名"}}}}` (day_index 从 0 计)
* `delete_attraction`: `{{"selector":{{"semantic":"景点名/类别"}}}}`
* `replace_attraction`: `{{"selector":{{"semantic":"旧景点"}},"target":{{"semantic":"新景点"}}}}`
* `replace_meal`: `{{"selector":{{"name":"欢喜面馆","day_index":0}},"target":{{"semantic":"火锅"}}}}`。餐饮替换时，`target.semantic` 是唯一检索关键词，可包含菜品、餐厅名、地点等用户明确诉求；不要生成“非面类”“不含面”等排除词，不要人为划分餐饮类别。若用户只说“换一家”，`semantic` 可填“餐厅”作为通用检索词。
* `update_dates`: `{{"fields":{{"start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}}}}`
* `full_replan`: 全局重排，无附加字段

**输出 JSON 结构:**
{{
"reply": "自然友好的用户回复",
"intent": "chat | replan",
"change_request": "变更摘要(普通聊天填 null)",
"change_set": {{ "operations": [...] }} | null,
"top_suggestions": ["建议1", "建议2", "建议3"],
"preference": {{ "prompt": "用户偏好描述" }} | null,
"done": false
}}

**示例 1 (具体调整: 删改并存):**
用户: "把第2天的博物馆换成深圳技术大学"
输出: {{"reply":"已为您替换为深圳技术大学。","intent":"replan","change_request":"第2天博物馆替换为深圳技术大学","change_set":{{"operations":[{{"operation":"replace_attraction","selector":{{"semantic":"博物馆"}},"target":{{"semantic":"深圳技术大学"}}}}]}},"top_suggestions":["推荐大学周边美食","调整第2天节奏为轻松","查看校园参观须知"],"preference":null,"done":false}}

**示例 2 (泛改请求: 整体重排):**
用户: "帮我重新安排一下行程"
输出: {{"reply":"好的，我会基于当前行程重新规划一版路线。","intent":"replan","change_request":"重新规划当前行程","change_set":{{"operations":[{{"operation":"full_replan"}}]}},"top_suggestions":["这次偏向自然风光","保持每天两个景点","加入本地美食"],"preference":null,"done":true}}

**示例 3 (咨询问题: 必须是 chat):**
用户: "请问博物馆周一闭馆吗"
输出: {{"reply":"大多数博物馆周一闭馆，具体以目的地场馆公告为准。","intent":"chat","change_request":null,"change_set":null,"top_suggestions":["推荐几家本地博物馆","查一下开放日门票","加入第二天的行程"],"preference":null,"done":false}}

**示例 4 (日期确认):**
助手上一轮: "新日期 5月10日 至 5月12日 可以吗？"
用户: "好的，就这几天"
输出: {{"reply":"好的，我已按确认的新日期调整行程。","intent":"replan","change_request":"确认新的出行日期","change_set":{{"operations":[{{"operation":"update_dates","fields":{{"start_date":"2026-05-10","end_date":"2026-05-12"}}}}]}},"top_suggestions":["看看新日期的天气","重新排每天的路线","推荐住宿"],"preference":null,"done":true}}

## 当前任务
**Question:** {question}

## 执行历史
{history}
"""

SUGGESTION_AGENT_PROMPT = """你是「行旅天下」的旅行建议生成器。
根据提供的目的地、当前行程、对话历史和已知偏好，生成恰好 3 条彼此不同、可直接点击发送的中文建议。
建议应具体关联已有行程和最近对话，避免泛泛而谈、避免固定模板，也不要假设用户尚未说过的偏好。
只返回 JSON，不要 Markdown 或解释：
{"top_suggestions":["建议1","建议2","建议3"]}

**示例：**
{"top_suggestions":["把深圳技术大学安排在第二天上午","补充大学附近人均 40 元以内的午餐","将第三天调整为轻松的室内路线"]}
"""

PLAN_PROMPT = """你是一个具备推理和行动能力的AI助手。你可以通过思考分析问题，然后调用合适的工具来获取信息，最终给出准确的答案。

## 可用工具
{tools}

## 工作流程
请严格按照以下格式进行回应，每次只能执行一个步骤：

Thought: 分析问题，确定需要什么信息，制定研究策略。
Action: 选择合适的工具获取信息，格式为：
- `{{tool_name}}[{{tool_input}}]`：调用工具获取信息。
- `Finish[TalkResponse]`：当你有足够信息得出结论时。TalkResponse为JSON格式，schema 如下
    success: bool = Field(default=True, description="是否成功")
    reply: str = Field(default="", description="assistant 回复")
    intent: str = Field(default="chat", description="语义意图: chat / replan")
    change_request: Optional[str] = Field(default=None, description="提炼后的行程修改要求")
    change_set: Optional[ChangeSet] = Field(default=None, description="LLM 输出的结构化计划操作")
    top_suggestions: List[str] = Field(default_factory=list, description="基于当前会话记忆生成的 3 条后续建议")
    preference: Optional["Preference"] = Field(default=None, description="提炼出的偏好")
    done: bool = Field(default=False, description="偏好是否收集完成")
    messages: List[ChatMessage] = Field(default=[], description="持久化后的完整聊天记录")

## 重要提醒
1. 每次回应必须包含Thought和Action两部分
2. 工具调用的格式必须严格遵循：工具名[参数]
3. 只有当你确信有足够信息回答问题时，才使用Finish
4. 如果工具返回的信息不够，继续使用其他工具或相同工具的不同参数

## 当前任务
**Question:** {question}

## 执行历史
{history}

现在开始你的推理和行动："""


def build_talk_prompt(request: TalkRequest) -> str:
    """用当前会话上下文填充 TALK_AGENT_PROMPT 的 {question}/{history} 占位符。

    模板中的字面 JSON 大括号已转义为 {{ }}，这里只负责填充两个命名占位符。
    """
    context_lines = []
    if request.city:
        context_lines.append(
            f"[目的地城市] {request.city}（用户提到大学、公园、酒店等未带城市的地点时，"
            "必须理解为该目的地范围内的地点）"
        )
    if request.plan_context:
        context_lines.append(
            "[当前行程摘要] " + request.plan_context
            + "（当前行程事实，仅以此为准解析‘第几天’、已有景点和住宿餐饮；"
            "不要把聊天历史中的建议当成已执行安排）"
        )
    if request.preference and request.preference.prompt:
        context_lines.append(f"[已知长期偏好] {request.preference.prompt}")
    for msg in request.messages:
        role = "用户" if msg.role == "user" else "顾问"
        context_lines.append(f"{role}: {msg.content}")
    history = "\n".join(context_lines) if context_lines else "（无）"
    return TALK_AGENT_PROMPT.format(question=request.message, history=history)


class PlanAgent(SimpleAgent):
    """旅行规划智能体：ReAct 规划 + 偏好对话（唯一对话入口 talk()）"""

    def __init__(self) -> None:
        self.llm = get_llm()

        # 对话 Agent（talk() 入口使用）。完整行为准则随每轮 format 后的
        # TALK_AGENT_PROMPT 作为用户消息传入，system 侧只保留角色行，
        # 避免模板占位符以未填充状态进入 system 提示。
        self.agent = SimpleAgent(
            name="旅行偏好顾问",
            llm=self.llm,
            system_prompt="你是「行旅天下」旅行偏好顾问，严格按用户消息中给出的行为准则输出纯 JSON。",
        )
        self.suggestion_agent = SimpleAgent(
            name="旅行建议生成器",
            llm=self.llm,
            system_prompt=SUGGESTION_AGENT_PROMPT,
        )

        # ReAct 规划工具链（自原 PlanAgent 移植）
        self.validate_agent = ValidateAgent()
        self.result: Any = None

        tool_registry = ToolRegistry()
        tool_registry.register_tool(SearchAttraction())
        tool_registry.register_tool(SearchWeather())
        tool_registry.register_tool(SearchHotel())
        tool_registry.register_tool(SearchRestaurant())
        self.react_agent = ReActAgent("旅行规划师", self.llm, tool_registry, max_steps=8, custom_prompt=PLAN_PROMPT)

    def run(self, input_text: str, max_tool_iterations: int=3, **kwargs) -> str:
        response = self.react_agent.run(input_text)
        return response

    # ============ 对话入口 ============

    def talk(self, request: TalkRequest) -> TalkResponse:
        """处理一轮对话，识别意图并产出结构化行程修改。

        Args:
            request: 含历史对话与本轮用户输入

        Returns:
            assistant 回复；replan 时附带 ChangeSet；偏好足够时置 done=True
        """
        try:
            prompt = build_talk_prompt(request)
            raw_reply = self.agent.run(prompt)
            parsed = self._parse_reply(raw_reply)
            print(
                "PlanAgent 结构化结果: "
                f"intent={parsed['intent']}; "
                f"operations={len(parsed['change_set'].operations) if parsed['change_set'] else 0}"
            )
            # 每轮对话都应提供可点击的动态 Top3。主对话模型偶尔会遗漏
            # top_suggestions 字段，此时使用同一会话上下文单独生成建议，
            # 不以固定文案冒充推荐。
            if len(parsed["top_suggestions"]) != 3:
                parsed["top_suggestions"] = self.generate_suggestions(
                    TalkRequest(
                        conversation_id=request.conversation_id,
                        city=request.city,
                        plan_context=request.plan_context,
                        preference=request.preference,
                        messages=[
                            *request.messages,
                            TalkMessage(role="user", content=request.message),
                            TalkMessage(role="assistant", content=parsed["reply"]),
                        ],
                        message="",
                    )
                )
            return TalkResponse(
                success=True,
                reply=parsed["reply"],
                intent=parsed["intent"],
                change_request=parsed["change_request"],
                change_set=parsed["change_set"],
                top_suggestions=parsed["top_suggestions"],
                preference=parsed["preference"],
                done=parsed["done"],
            )
        except Exception as error:
            print(f"⚠️ 偏好对话失败，使用兜底回复: {type(error).__name__}: {error}")
            return TalkResponse(
                success=True,
                reply="我暂时没能理解这次修改要求，请换一种说法再试一次。",
                preference=self._extract_preference(request.message),
                intent="chat",
                change_request=None,
                change_set=None,
                top_suggestions=[],
                done=False,
            )

    def generate_suggestions(self, request: TalkRequest) -> list[str]:
        """从已持久化的会话记忆恢复动态 Top3，不写入聊天记录。"""
        try:
            raw_reply = self.suggestion_agent.run(self._build_suggestion_prompt(request))
            return self._parse_suggestions(raw_reply)
        except Exception as error:
            print(f"⚠️ Top3 建议生成失败: {type(error).__name__}: {error}")
            return []

    # ============ 提示构造 ============

    def _build_suggestion_prompt(self, request: TalkRequest) -> str:
        lines = [f"当前旅行计划目的地: {request.city or '未提供'}。"]
        if request.plan_context:
            lines.append(
                "当前行程摘要（当前行程事实，仅以此为准解析‘第几天’、已有景点和住宿餐饮；"
                "不要把聊天历史中的建议当成已执行安排）: "
                + request.plan_context
            )
        if request.preference and request.preference.prompt:
            lines.append(f"已知长期偏好: {request.preference.prompt}")
        if request.messages:
            lines.append("聊天历史:")
            for msg in request.messages:
                role = "用户" if msg.role == "user" else "行旅助手"
                lines.append(f"{role}: {msg.content}")
        else:
            lines.append("聊天历史为空；请仅根据当前行程提供下一步可调整项。")
        lines.append("现在生成恰好 3 条建议。")
        return "\n".join(lines)

    # ============ 结构化输出解析 ============

    def _parse_reply(self, raw_reply: str) -> dict[str, Any]:
        """解析结构化语义结果；解析失败时安全降级为普通聊天。"""
        text = (raw_reply or "").strip()
        try:
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("未找到 JSON 对象")
            data = json.loads(text[start:end + 1])
            intent = data.get("intent")
            if intent not in {"chat", "replan"}:
                raise ValueError(f"intent 必须是 chat 或 replan，得到: {intent}")

            preference_data = data.get("preference")
            preference = None
            if isinstance(preference_data, dict) and preference_data.get("prompt"):
                preference = Preference(prompt=str(preference_data["prompt"]).strip())
            elif isinstance(preference_data, str) and preference_data.strip():
                preference = Preference(prompt=preference_data.strip())

            change_request = data.get("change_request")
            change_set_data = data.get("change_set")
            change_set = None

            if change_set_data:
                try:
                    change_set = ChangeSet.model_validate(change_set_data)
                    print(f"✅ change_set 解析成功: operations={len(change_set.operations)}")
                except Exception as e:
                    print(f"⚠️ change_set 验证失败，降级为普通聊天: {e}，原始数据: {change_set_data}")
                    return {
                        "reply": str(data.get("reply") or "好的，我记下了。"),
                        "intent": "chat",
                        "change_request": None,
                        "change_set": None,
                        "top_suggestions": [],
                        "preference": preference,
                        "done": False,
                    }

            if intent == "replan" and change_set is None:
                print("⚠️ replan 缺少有效 change_set，降级为普通聊天")
                return {
                    "reply": str(data.get("reply") or "好的，我记下了。"),
                    "intent": "chat",
                    "change_request": None,
                    "change_set": None,
                    "top_suggestions": [],
                    "preference": preference,
                    "done": False,
                }

            if intent == "chat":
                change_set = None

            raw_suggestions = data.get("top_suggestions") or []
            top_suggestions = []
            if isinstance(raw_suggestions, list):
                top_suggestions = list(dict.fromkeys(
                    str(item).strip() for item in raw_suggestions if str(item).strip()
                ))[:3]

            if intent == "replan":
                print(
                    "识别为重规划: "
                    f"operations={len(change_set.operations) if change_set else 0}"
                )

            return {
                "reply": str(data.get("reply") or "好的，我记下了。"),
                "intent": intent,
                "change_request": str(change_request).strip() if change_request else None,
                "change_set": change_set,
                "top_suggestions": top_suggestions,
                "preference": preference,
                "done": bool(data.get("done", preference is not None)),
            }
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"⚠️ 结构化输出解析失败，按普通聊天处理: {error}")
            print(f"   原始输出: {text[:200]}")
            return {
                "reply": text or "好的，我记下了。",
                "intent": "chat",
                "change_request": None,
                "change_set": None,
                "top_suggestions": [],
                "preference": None,
                "done": False,
            }

    @staticmethod
    def _parse_suggestions(raw_reply: str) -> list[str]:
        text = (raw_reply or "").strip()
        try:
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("未找到 JSON 对象")
            data = json.loads(text[start:end + 1])
            values = data.get("top_suggestions")
            if not isinstance(values, list):
                raise ValueError("top_suggestions 必须是数组")
            suggestions = list(dict.fromkeys(
                str(item).strip() for item in values if str(item).strip()
            ))
            if len(suggestions) != 3:
                raise ValueError("top_suggestions 必须恰好包含 3 条建议")
            return suggestions
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"Top3 建议结构化输出解析失败: {error}")
            return []

    # ============ 兜底 ============

    @staticmethod
    def _extract_preference(text: str) -> Preference:
        """兜底:把任意文本转成 Preference。"""
        return Preference(prompt=(text or "").strip())


# 全局对话智能体实例(单例模式，生命周期与后端同寿)
_plan_agent = None


def get_plan_agent() -> PlanAgent:
    """ 获取旅行规划智能体实例(单例模式) """
    print("🔄 获取旅行规划智能体实例...")
    global _plan_agent

    if _plan_agent is None:
        _plan_agent = PlanAgent()

    return _plan_agent
