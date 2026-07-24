"""偏好对话智能体

与用户多轮对话，从聊天中提炼出「用户偏好提示词」，
供 TripPlannerAgent.plan_trip 使用。不依赖高德 MCP 工具，构造轻量。
"""

from ..services.llm_service import get_llm
import json
from typing import Any

from ..models.schemas import Preference, TalkRequest, TalkResponse

from hello_agents import SimpleAgent

# ============ Agent提示词 ============

TALK_AGENT_PROMPT = f"""你是「行旅天下」的旅行偏好顾问。你的任务是通过自然、友好的多轮对话，
了解用户的旅行偏好，最终凝练成一段可供行程规划使用的偏好提示词。

**你需要逐步了解(不要一次全问，围绕用户回答自然追问):**
1. 兴趣类型(历史文化 / 自然风光 / 美食 / 购物 / 艺术 / 休闲等)
2. 节奏偏好(悠闲 / 紧凑 / 打卡为主)
3. 忌口或饮食偏好、身体/无障碍需求
4. 预算与住宿档次倾向
5. 同行人员(独自 / 情侣 / 家庭带娃 / 朋友)等其他关键约束

**语义判定规则:**
1. 如果用户只是询问、闲聊、询问建议或了解目的地信息，intent 填 "chat"。
2. 如果用户要求修改景点、日期、交通、住宿、餐饮、预算或某一天的安排，intent 填 "replan"。
3. intent 为 "replan" 时，change_request 必须是清晰、完整的修改要求。
4. intent 为 "chat" 时，change_request 必须为 null。

**对话规则:**
1. 每轮只温和地追问 1-2 个问题，语气亲切自然，避免一次抛出一长串问题。
2. preference.prompt 只填写从对话中提炼出的稳定旅行偏好；没有新偏好时填 null。
3. 只返回 JSON，不要返回 Markdown 代码块或 JSON 以外的文字。

**严格返回格式:**
{{
  "reply": "给用户看的自然语言回复",
  "intent": "chat 或 replan",
  "change_request": "完整的行程修改要求，普通聊天时为 null",
  "preference": {{"prompt": "稳定的用户旅行偏好"}} 或 null,
  "done": true 或 false
}}

**示例:**
{{"reply":"我会把第二天调整为自然风光路线。","intent":"replan","change_request":"将第二天改为自然风光路线","preference":{{"prompt":"偏好自然风光"}},"done":true}}
"""


class TalkAgent:
    """旅行偏好对话智能体"""

    def __init__(self):
        """初始化对话 Agent(无 MCP 工具)"""
        print("🔄 初始化偏好对话智能体...")
        self.llm = get_llm()
        self.agent = SimpleAgent(
            name="旅行偏好顾问",
            llm=self.llm,
            system_prompt=TALK_AGENT_PROMPT,
        )
        print("✅ 偏好对话智能体初始化成功")

    def chat(self, request: TalkRequest) -> TalkResponse:
        """处理一轮对话。

        Args:
            request: 含历史对话与本轮用户输入

        Returns:
            assistant 回复；若已收集充分则附带提炼出的 Preference 并置 done=True
        """
        try:
            prompt = self._build_prompt(request)
            raw_reply = self.agent.run(prompt)
            parsed = self._parse_reply(raw_reply)
            return TalkResponse(
                success=True,
                **parsed,
            )
        except Exception as error:
            print(f"⚠️ 偏好对话失败，使用兜底回复: {type(error).__name__}: {error}")
            # 降级:把用户本轮输入直接作为偏好，保证链路可用
            return TalkResponse(
                success=True,
                reply="好的，我已经记下你的偏好啦，可以直接开始规划行程～",
                preference=self.extract_preference(request.message),
                intent="chat",
                change_request=None,
                done=False,
            )

    def _build_prompt(self, request: TalkRequest) -> str:
        """把历史对话与本轮输入拼成一段上下文提示。"""
        lines = []
        for msg in request.messages:
            role = "用户" if msg.role == "user" else "顾问"
            lines.append(f"{role}: {msg.content}")
        lines.append(f"用户: {request.message}")
        history = "\n".join(lines)
        return f"以下是与用户的对话记录，请根据系统设定继续本轮回复:\n\n{history}"

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
                raise ValueError("intent 必须是 chat 或 replan")
            preference_data = data.get("preference")
            preference = None
            if isinstance(preference_data, dict) and preference_data.get("prompt"):
                preference = Preference(prompt=str(preference_data["prompt"]).strip())
            elif isinstance(preference_data, str) and preference_data.strip():
                preference = Preference(prompt=preference_data.strip())
            change_request = data.get("change_request")
            if intent == "replan" and not str(change_request or "").strip():
                raise ValueError("replan 缺少 change_request")
            return {
                "reply": str(data.get("reply") or "好的，我记下了。"),
                "intent": intent,
                "change_request": str(change_request).strip() if change_request else None,
                "preference": preference,
                "done": bool(data.get("done", preference is not None)),
            }
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"talk_agent 结构化输出解析失败，按普通聊天处理: {error}")
            return {
                "reply": text or "好的，我记下了。",
                "intent": "chat",
                "change_request": None,
                "preference": None,
                "done": False,
            }

    @staticmethod
    def extract_preference(text: str) -> Preference:
        """兜底:把任意文本转成 Preference。"""
        return Preference(prompt=(text or "").strip())


# 全局对话智能体实例(单例模式)
_talk_agent = None


def get_talk_agent() -> TalkAgent:
    """获取偏好对话智能体实例(单例模式)"""
    global _talk_agent

    if _talk_agent is None:
        _talk_agent = TalkAgent()

    return _talk_agent
