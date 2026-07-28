"""偏好对话智能体

与用户多轮对话，从聊天中提炼出「用户偏好提示词」，
供 TripPlannerAgent.plan_trip 使用。不依赖高德 MCP 工具，构造轻量。
"""

from ..services.llm_service import get_llm
import json
from typing import Any

from ..models.schemas import ChangeSet, Preference, TalkMessage, TalkRequest, TalkResponse

from hello_agents import SimpleAgent

# ============ Agent提示词 ============

TALK_AGENT_PROMPT = """你是「行旅天下」的旅行偏好顾问。你的任务是通过自然、友好的多轮对话，
了解用户的旅行偏好，最终凝练成一段可供行程规划使用的偏好提示词。

**你需要逐步了解(不要一次全问，围绕用户回答自然追问):**
1. 兴趣类型(历史文化 / 自然风光 / 美食 / 购物 / 艺术 / 休闲等)
2. 节奏偏好(悠闲 / 紧凑 / 打卡为主)
3. 忌口或饮食偏好、身体/无障碍需求
4. 预算与住宿档次倾向
5. 同行人员(独自 / 情侣 / 家庭带娃 / 朋友)等其他关键约束

**变更判定与 ChangeSet 规则:**
1. 询问、闲聊或咨询建议时，intent 填 "chat"，change_set 填 null。
2. **关键：用户表达改计划、调整、替换、删除、增加、合并、移到等修改意图时，intent 必须填 replan，直接输出可执行的 change_set，禁止追问。**
3. 只能使用以下 operation: add_attraction、delete_attraction、replace_attraction、update_day、full_replan。
4. **删除景点**：使用 delete_attraction，selector.semantic 指定要删除的景点名称或类别。例如"删除寺庙" → {"operation":"delete_attraction","selector":{"semantic":"寺庙"}}
5. **替换景点**：使用 replace_attraction，selector 指向旧景点，target 指向新景点。例如"把马峦山改为大学" → {"operation":"replace_attraction","selector":{"semantic":"马峦山"},"target":{"semantic":"大学"}}
6. **添加景点**：使用 add_attraction，selector.day_index 指定添加到第几天（从0开始），target 指定新景点。例如"第2天添加大学" → {"operation":"add_attraction","selector":{"day_index":1},"target":{"semantic":"深圳技术大学"}}
7. **用户只说我要改计划且没有具体修改内容时，输出 full_replan**。禁止输出 SQL、正则表达式或自然语言操作说明。

**对话规则:**
1. 每轮只温和地追问 1-2 个问题，语气亲切自然，避免一次抛出一长串问题。
2. preference.prompt 只填写从对话中提炼出的稳定旅行偏好；没有新偏好时填 null。
3. 只返回 JSON，不要返回 Markdown 代码块或 JSON 以外的文字。
4. top_suggestions 必须基于对话历史、当前行程摘要和已知偏好，返回 3 条彼此不同、可直接点击发送的下一步建议；禁止使用固定模板。

**严格返回格式:**
{
  "reply": "给用户看的自然语言回复",
  "intent": "chat 或 replan",
  "change_request": "给日志和用户看的简短变更摘要，普通聊天时为 null",
  "change_set": {
    "operations": [
      {"operation": "delete_attraction", "selector": {"semantic": "寺庙"}}
    ]
  } 或 null,
  "top_suggestions": ["建议1", "建议2", "建议3"],
  "preference": {"prompt": "稳定的用户旅行偏好"} 或 null,
  "done": true 或 false
}

**示例 1 (删除):**
用户："把第2天的深圳自然博物馆删掉，改成技术大学校园"
回复：{"reply":"好的，我来调整行程。删除第2天的深圳自然博物馆，添加深圳技术大学校园。","intent":"replan","change_request":"删除第2天博物馆，添加技术大学校园","change_set":{"operations":[{"operation":"delete_attraction","selector":{"semantic":"深圳自然博物馆"}},{"operation":"add_attraction","selector":{"day_index":1},"target":{"semantic":"深圳技术大学"}}]},"top_suggestions":["把校园参观安排在上午","添加附近餐饮","查看校园附近的景点"],"preference":null,"done":true}

**示例 2 (合并):**
用户："把第2天的博物馆调到第1天下午，和马峦山合一天"
回复：{"reply":"好的，我把博物馆移到第1天下午。","intent":"replan","change_request":"把博物馆从第2天移到第1天下午","change_set":{"operations":[{"operation":"delete_attraction","selector":{"semantic":"深圳自然博物馆"}},{"operation":"add_attraction","selector":{"day_index":0},"target":{"semantic":"深圳自然博物馆"}}]},"top_suggestions":["第1天会不会太紧张了","把第2天安排得更轻松","增加第2天的其他景点"],"preference":null,"done":true}

**示例 3 (添加):**
用户："把大学加到第2天"
回复：{"reply":"好的，我把深圳技术大学加到第2天。","intent":"replan","change_request":"第2天添加深圳技术大学","change_set":{"operations":[{"operation":"add_attraction","selector":{"day_index":1},"target":{"semantic":"深圳技术大学"}}]},"top_suggestions":["安排在上午还是下午","附近有什么好吃的","第2天还需要调整吗"],"preference":null,"done":true}
"""

SUGGESTION_AGENT_PROMPT = """你是「行旅天下」的旅行建议生成器。
根据提供的目的地、当前行程、对话历史和已知偏好，生成恰好 3 条彼此不同、可直接点击发送的中文建议。
建议应具体关联已有行程和最近对话，避免泛泛而谈、避免固定模板，也不要假设用户尚未说过的偏好。
只返回 JSON，不要 Markdown 或解释：
{"top_suggestions":["建议1","建议2","建议3"]}

**示例：**
{"top_suggestions":["把深圳技术大学安排在第二天上午","补充大学附近人均 40 元以内的午餐","将第三天调整为轻松的室内路线"]}
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
        self.suggestion_agent = SimpleAgent(
            name="旅行建议生成器",
            llm=self.llm,
            system_prompt=SUGGESTION_AGENT_PROMPT,
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
                preference=self.extract_preference(request.message),
                intent="chat",
                change_request=None,
                change_set=None,
                top_suggestions=[],
                done=False,
            )

    def _build_prompt(self, request: TalkRequest) -> str:
        """把历史对话与本轮输入拼成一段上下文提示。"""
        lines = []
        if request.city:
            lines.append(
                f"当前旅行计划目的地: {request.city}。用户提到大学、公园、酒店等未带城市的地点时，"
                "必须理解为该目的地范围内的地点。"
            )
        if request.plan_context:
            lines.append(f"当前行程摘要: {request.plan_context}")
        if request.preference and request.preference.prompt:
            lines.append(f"已知长期偏好: {request.preference.prompt}")
        for msg in request.messages:
            role = "用户" if msg.role == "user" else "顾问"
            lines.append(f"{role}: {msg.content}")
        lines.append(f"用户: {request.message}")
        history = "\n".join(lines)
        return f"以下是与用户的对话记录，请根据系统设定继续本轮回复:\n\n{history}"

    def generate_suggestions(self, request: TalkRequest) -> list[str]:
        """从已持久化的会话记忆恢复动态 Top3，不写入聊天记录。"""
        try:
            raw_reply = self.suggestion_agent.run(self._build_suggestion_prompt(request))
            return self._parse_suggestions(raw_reply)
        except Exception as error:
            print(f"⚠️ Top3 建议生成失败: {type(error).__name__}: {error}")
            return []

    def _build_suggestion_prompt(self, request: TalkRequest) -> str:
        lines = [f"当前旅行计划目的地: {request.city or '未提供'}。"]
        if request.plan_context:
            lines.append(f"当前行程摘要: {request.plan_context}")
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
                    print(f"🔍 解析 change_set，原始数据: {json.dumps(change_set_data, ensure_ascii=False)}")
                    change_set = ChangeSet.model_validate(change_set_data)
                    print(f"✅ change_set 解析成功: operations={len(change_set.operations)}")
                except Exception as e:
                    print(f"⚠️ change_set 验证失败: {e}，原始数据: {change_set_data}")
                    if intent == "replan":
                        raise ValueError(f"replan 的 change_set 验证失败: {e}")

            if intent == "replan" and change_set is None:
                raise ValueError(f"replan 缺少有效的 change_set（原始数据: {change_set_data}）")

            if intent == "chat":
                change_set = None

            raw_suggestions = data.get("top_suggestions") or []
            top_suggestions = []
            if isinstance(raw_suggestions, list):
                top_suggestions = list(dict.fromkeys(
                    str(item).strip() for item in raw_suggestions if str(item).strip()
                ))[:3]

            result = {
                "reply": str(data.get("reply") or "好的，我记下了。"),
                "intent": intent,
                "change_request": str(change_request).strip() if change_request else None,
                "change_set": change_set,
                "top_suggestions": top_suggestions,
                "preference": preference,
                "done": bool(data.get("done", preference is not None)),
            }

            if intent == "replan":
                print(f"✅ 识别为重规划意图: change_request={result['change_request']}, operations={len(change_set.operations) if change_set else 0}")

            return result
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"⚠️ talk_agent 结构化输出解析失败，按普通聊天处理: {error}")
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
