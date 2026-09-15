"""偏好对话智能体

与用户多轮对话，从聊天中提炼出「用户偏好提示词」，
供 TripPlannerAgent.plan_trip 使用。不依赖高德 MCP 工具，构造轻量。
"""

from ..services.llm_service import get_llm
from datetime import date
import json
import re
from typing import Any

from ..models.schemas import ChangeOperation, ChangeSet, Preference, TalkMessage, TalkRequest, TalkResponse
from .plan_agent import PlanAgent

from hello_agents import SimpleAgent

# ============ Agent提示词 ============

TALK_AGENT_PROMPT = """你是「行旅天下」旅行偏好顾问。通过自然多轮对话挖掘用户偏好（兴趣、节奏、饮食/禁忌、预算、同行人），并处理行程调整。

**核心行为准则:**

1. **意图判断**:
* 咨询/闲聊：`intent="chat"`, `change_set=null`。每轮仅追问 1~2 个未确认的偏好。
* 调整行程：`intent="replan"`, 直接输出 `change_set`，禁止反问确认。
* 泛改请求（如“重新安排”“改一下计划”）：直接返回 `{"operations":[{"operation":"full_replan"}]}`。


2. **偏好沉淀**: `preference.prompt` 仅收录已确认的稳定偏好，无更新则填 `null`。
3. **输出限制**: 仅输出纯 JSON，不含 Markdown 标记及其他文本。`top_suggestions` 固定返回 3 条具体且各异的快捷回复选项。

**ChangeSet 支持操作:**

* `add_attraction`: `{"selector":{"day_index":0},"target":{"semantic":"景点名"}}` (day_index 从 0 计)
* `delete_attraction`: `{"selector":{"semantic":"景点名/类别"}}`
* `replace_attraction`: `{"selector":{"semantic":"旧景点"},"target":{"semantic":"新景点"}}`
* `replace_meal`: `{"selector":{"name":"欢喜面馆","day_index":0},"target":{"semantic":"火锅"}}`。餐饮替换时，`target.semantic` 是唯一检索关键词，可包含菜品、餐厅名、地点等用户明确诉求；不要生成“非面类”“不含面”等排除词，不要人为划分餐饮类别。若用户只说“换一家”，`semantic` 可填“餐厅”作为通用检索词。
* `update_dates`: `{"fields":{"start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}}`
* `full_replan`: 全局重排，无附加字段

**输出 JSON 结构:**
{
"reply": "自然友好的用户回复",
"intent": "chat | replan",
"change_request": "变更摘要(普通聊天填 null)",
"change_set": { "operations": [...] } | null,
"top_suggestions": ["建议1", "建议2", "建议3"],
"preference": { "prompt": "用户偏好描述" } | null,
"done": false
}

**示例 (删改并存):**
用户: "把第2天的博物馆换成深圳技术大学"
输出: {"reply":"已为您替换为深圳技术大学。","intent":"replan","change_request":"第2天博物馆替换为深圳技术大学","change_set":{"operations":[{"operation":"replace_attraction","selector":{"semantic":"博物馆"},"target":{"semantic":"深圳技术大学"}}]},"top_suggestions":["推荐大学周边美食","调整第2天节奏为轻松","查看校园参观须知"],"preference":null,"done":false}
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

    def __init__(self, plan_agent: PlanAgent | None = None):
        """初始化对话 Agent(无 MCP 工具)"""
        print("🔄 初始化偏好对话智能体...")
        self.llm = get_llm()
        self.plan_agent = plan_agent or PlanAgent()
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

    # ============ 对话入口 ============

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
            confirmation_dates = self._date_confirmation(request)
            explicit_replan = self._has_explicit_replan_intent(request.message)
            negative_replan = self._is_negative_replan(request.message)
            gate_hit = self._is_explicit_full_replan(request.message)
            if confirmation_dates:
                parsed["reply"] = "好的，我已按确认的新日期调整行程。"
                parsed["intent"] = "replan"
                parsed["change_request"] = "确认新的出行日期"
                parsed["change_set"] = ChangeSet(operations=[ChangeOperation(
                    operation="update_dates",
                    fields={"start_date": confirmation_dates[0], "end_date": confirmation_dates[1]},
                )])
                parsed["done"] = True
            elif gate_hit and parsed["intent"] == "chat":
                parsed = self._force_full_replan(parsed)
            elif explicit_replan and not negative_replan and not parsed.get("_parse_failed") and parsed["intent"] == "chat":
                parsed["reply"] = "我识别到你想修改行程，但还没有生成可执行的修改方案，请再试一次。"
                parsed["intent"] = "replan"
                parsed["change_request"] = request.message.strip()
                parsed["change_set"] = None
                parsed["done"] = False
            print(
                "TalkAgent 结构化结果: "
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

    def talk(self, requirement: TalkRequest) -> TalkResponse:
        '''将对话上下文转交规划 Agent（旧版路径；生产路由使用 chat()）。

        Args:
            requirement: TalkRequest，包含历史对话与本轮用户输入

        Returns:
            TalkResponse，包含智能体回复、意图、变更集、Top3 建议、偏好提示词等
        '''
        requirement_prompt = requirement.message
        preference_prompt = requirement.preference.prompt if requirement.preference else ""
        if preference_prompt:
            print(f"偏好对话请求: message={requirement_prompt!r}; preference={preference_prompt[:120]!r}")
        else:
            print(f"偏好对话请求: message={requirement_prompt!r}")
        if hasattr(self.plan_agent, "plan"):
            return self.plan_agent.plan(
                self._create_prompt(requirement),
                preference_prompt,
            )
        talk_response_raw = self.plan_agent.run(
            requirement_prompt + preference_prompt
        )
        return json.loads(talk_response_raw)

    # ============ 提示构造 ============

    def _build_prompt(self, request: TalkRequest) -> str:
        """把历史对话与本轮输入拼成一段上下文提示。"""
        lines = []
        if request.city:
            lines.append(
                f"当前旅行计划目的地: {request.city}。用户提到大学、公园、酒店等未带城市的地点时，"
                "必须理解为该目的地范围内的地点。"
            )
        if request.plan_context:
            lines.append(
                "当前行程摘要（当前行程事实，仅以此为准解析‘第几天’、已有景点和住宿餐饮；"
                "不要把聊天历史中的建议当成已执行安排）: "
                + request.plan_context
            )
        if request.preference and request.preference.prompt:
            lines.append(f"已知长期偏好: {request.preference.prompt}")
        for msg in request.messages:
            role = "用户" if msg.role == "user" else "顾问"
            lines.append(f"{role}: {msg.content}")
        lines.append(f"用户: {request.message}")
        history = "\n".join(lines)
        return f"以下是与用户的对话记录，请根据系统设定继续本轮回复:\n\n{history}"

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

    def _create_prompt(self, requirement: TalkRequest) -> str:
        """talk() 专用：把请求转成规划 Agent 的输入提示。"""
        if isinstance(requirement, TalkRequest):
            return self._build_prompt(requirement)
        if hasattr(requirement, "model_dump"):
            payload = requirement.model_dump()
        elif isinstance(requirement, dict):
            payload = requirement
        else:
            return str(requirement or "").strip()
        return json.dumps(payload, ensure_ascii=False, default=str)

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
                "_parse_failed": False,
            }

            if intent == "replan":
                print(
                    "识别为重规划: "
                    f"operations={len(change_set.operations) if change_set else 0}"
                )

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
                "_parse_failed": True,
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

    # ============ 意图识别 ============

    @staticmethod
    def _normalized_message(text: str) -> str:
        return "".join((text or "").split()).lower()

    @classmethod
    def _has_explicit_replan_intent(cls, text: str) -> bool:
        """检测明确的计划修改动作，不猜测具体 ChangeSet。"""
        normalized = cls._normalized_message(text)
        if not normalized:
            return False
        if any(marker in normalized for marker in ("怎么改计划", "改计划怎么", "改计划接口", "改计划是什么")):
            return False
        positive_markers = (
            "删除", "删掉", "去掉", "取消", "不安排", "增加", "添加", "加一个",
            "补充", "替换", "换成", "改成", "移到", "调到", "调整", "修改",
            "改期", "出发日期", "结束日期", "提前", "推迟", "重新安排", "重新规划",
            "改计划", "改行程",
        )
        return any(marker in normalized for marker in positive_markers)

    @classmethod
    def _is_negative_replan(cls, text: str) -> bool:
        normalized = cls._normalized_message(text)
        if not normalized:
            return False
        negative = ("不想改", "不要改", "不用改", "先别改", "暂时不改")
        if not any(marker in normalized for marker in negative):
            return False
        positive = ("但", "但是", "不过", "请把", "请将", "改成", "换成", "删除", "增加", "添加")
        return not any(marker in normalized for marker in positive)

    @classmethod
    def _is_explicit_full_replan(cls, text: str) -> bool:
        """识别没有具体目标、但明确要求整体重规划的短请求。"""
        normalized = cls._normalized_message(text)
        if not normalized or cls._is_negative_replan(text):
            return False
        if any(marker in normalized for marker in ("怎么改计划", "改计划怎么", "改计划接口", "改计划是什么")):
            return False
        phrases = (
            "我要改计划", "我想改计划", "帮我改计划", "把计划改一下", "把行程改一下",
            "我想调整行程", "帮我调整行程", "重新安排一下", "重新规划一下", "我想重新规划",
        )
        return any(phrase in normalized for phrase in phrases)

    @classmethod
    def _date_confirmation(cls, request: TalkRequest) -> tuple[str, str] | None:
        if not request.messages or not any(msg.role == "assistant" for msg in request.messages):
            return None
        if not any(marker in cls._normalized_message(request.message) for marker in ("确认", "好的", "可以", "按这个", "就这样")):
            return None
        text = "\n".join(msg.content for msg in request.messages if msg.role == "assistant")
        match = re.search(
            r"(?:新日期|日期)[^0-9]{0,12}(\d{1,2})月(?:\d{1,2})日[^至\-—]*[至\-—]\s*(\d{1,2})月(?:\d{1,2})日",
            text,
        )
        if not match:
            return None
        year_match = re.search(r"(20\d{2})-\d{2}-\d{2}", request.plan_context or "")
        year = int(year_match.group(1)) if year_match else date.today().year
        start_month, end_month = int(match.group(1)), int(match.group(2))
        start = date(year, start_month, 1)
        end = date(year, end_month, 1)
        start_day = int(re.search(rf"{start_month}月(\d{{1,2}})日", text).group(1))
        end_day = int(re.findall(rf"{end_month}月(\d{{1,2}})日", text)[-1])
        return date(year, start_month, start_day).isoformat(), date(year, end_month, end_day).isoformat()

    @staticmethod
    def _force_full_replan(parsed: dict[str, Any]) -> dict[str, Any]:
        """为明确的整体改计划请求补齐稳定的结构化契约。"""
        parsed = dict(parsed)
        parsed["reply"] = "好的，我会基于当前行程重新规划一版路线。"
        parsed["intent"] = "replan"
        parsed["change_request"] = "重新规划当前行程"
        parsed["change_set"] = ChangeSet(
            operations=[ChangeOperation(operation="full_replan")]
        )
        parsed["done"] = True
        return parsed

    # ============ 兜底 ============

    @staticmethod
    def _extract_preference(text: str) -> Preference:
        """兜底:把任意文本转成 Preference。"""
        return Preference(prompt=(text or "").strip())


# 全局对话智能体实例(单例模式，生命周期与后端同寿)
_talk_agent = None


def get_talk_agent() -> TalkAgent:
    """ 获取对话智能体实例(单例模式) """
    print("🔄 获取对话智能体实例...")
    global _talk_agent

    if _talk_agent is None:
        _talk_agent = TalkAgent()

    return _talk_agent
