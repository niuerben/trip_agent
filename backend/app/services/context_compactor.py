"""Talk 上下文窗口压缩：16k 字符窗口 + 超限 LLM 滚动摘要。

约定：中文场景按字符数近似 token 数（1 字 ≈ 1 token），不做提前压缩
余量——只有提示词总长超过窗口才触发压缩。压缩只针对聊天历史：
plan_context、长期偏好等头部上下文优先保留；历史按"最近 N 条原文 +
更早内容滚动摘要"组织，摘要按会话缓存在内存中增量更新。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable

from ..config import get_settings
from ..models.schemas import TalkMessage, TalkRequest

# 摘要生成提示词：只提取对后续行程对话有用的事实，丢弃寒暄和重复。
SUMMARY_SYSTEM_PROMPT = (
    "你是旅行对话摘要器。把多轮旅行偏好对话压缩成要点摘要，保留：目的地、"
    "出行日期、同行人、已确认的偏好与禁忌、预算、已执行的行程修改、"
    "尚未落实的意向。丢弃寒暄、重复与无效内容。直接输出摘要正文，"
    "不要解释，不要 Markdown，长度不超过 300 字。"
)


def estimate_tokens(text: str) -> int:
    """按字符数近似 token 数。"""
    return len(text or "")


class ContextCompactor:
    """把 TalkRequest 的聊天历史压进固定字符窗口。

    Args:
        llm: 用于生成滚动摘要的 LLM 实例；为 None 时只能硬截断。
        summarizer: 测试注入点，签名 ``(text: str) -> str``；提供后优先于 llm。
    """

    def __init__(self, llm: Any = None, summarizer: Callable[[str], str] | None = None) -> None:
        self._llm = llm
        self._summarizer = summarizer
        # conversation_id -> (已摘要的消息条数, 摘要文本)。仅进程内缓存，
        # 重启后重新摘要只多一次 LLM 调用，不影响正确性。
        self._summary_cache: OrderedDict[str, tuple[int, str]] = OrderedDict()

    def compact_messages(
        self,
        request: TalkRequest,
        history_budget: int,
    ) -> tuple[list[str], str | None]:
        """把历史消息压进 history_budget 字符，返回 (对话行, 摘要文本)。

        对话行可直接作为提示词的历史段落；摘要文本为 None 表示未触发压缩。
        压缩失败（LLM 异常）时降级为丢弃最旧消息的硬截断，保证窗口不被突破。
        """
        settings = get_settings()
        keep_recent = max(2, settings.talk_context_keep_recent_messages)
        lines = [self._format_message(msg) for msg in request.messages]
        total = sum(estimate_tokens(line) + 1 for line in lines)
        if total <= history_budget:
            return lines, None

        recent_lines = lines[-keep_recent:]
        old_messages = request.messages[:-keep_recent]
        if not old_messages:
            # 没有可摘要的旧内容，只能从最旧开始丢。
            return self._truncate_from_front(recent_lines, history_budget), None

        summary = self._rolling_summary(request.conversation_id, old_messages)
        summary_line = f"[更早对话摘要] {summary}" if summary else None
        if summary_line is None:
            # 摘要生成失败：硬截断旧消息，只保留最近原文。
            return self._truncate_from_front(recent_lines, history_budget), None

        if estimate_tokens(summary_line) + 1 > history_budget:
            # 极端场景：摘要本身就超预算（几乎不可能），截断摘要。
            summary = summary[: max(0, history_budget - len("[更早对话摘要] ") - 1)]
            summary_line = f"[更早对话摘要] {summary}"
        kept = list(recent_lines)
        result_lines = [summary_line, *kept]
        while estimate_tokens("\n".join(result_lines)) > history_budget and len(kept) > 1:
            # 摘要 + 最近原文仍超限：继续丢最旧的原文。
            kept = kept[1:]
            result_lines = [summary_line, *kept]
        return result_lines, summary

    def _format_message(self, msg: TalkMessage) -> str:
        role = "用户" if msg.role == "user" else "顾问"
        return f"{role}: {msg.content}"

    @staticmethod
    def _truncate_from_front(lines: list[str], budget: int) -> list[str]:
        """从最旧开始丢弃，直到总长不超预算；至少保留最新一条。"""
        kept = list(lines)
        while estimate_tokens("\n".join(kept)) > budget and len(kept) > 1:
            kept = kept[1:]
        return kept

    def _rolling_summary(self, conversation_id: str | None, old_messages: list[TalkMessage]) -> str | None:
        """增量摘要旧消息：复用缓存中已覆盖部分的摘要，只摘要新增片段。"""
        covered = 0
        previous = ""
        if conversation_id:
            cached = self._summary_cache.get(conversation_id)
            if cached and cached[0] <= len(old_messages):
                covered, previous = cached
        new_messages = old_messages[covered:]
        if not new_messages and previous:
            return previous

        transcript = "\n".join(self._format_message(msg) for msg in new_messages)
        prompt = (
            f"已有摘要（可能为空）：\n{previous or '（无）'}\n\n"
            f"新增对话：\n{transcript}\n\n请输出合并后的摘要。"
        )
        try:
            summary = self._summarize(prompt)
        except Exception as error:
            print(f"⚠️ 历史摘要生成失败，降级为硬截断: {type(error).__name__}: {error}")
            return None
        if not summary:
            return None
        if conversation_id:
            self._remember_summary(conversation_id, len(old_messages), summary)
        return summary

    def _summarize(self, prompt: str) -> str:
        if self._summarizer is not None:
            return str(self._summarizer(prompt)).strip()
        if self._llm is None:
            raise RuntimeError("未配置摘要 LLM")
        from hello_agents import SimpleAgent

        agent = SimpleAgent(
            name="旅行对话摘要器",
            llm=self._llm,
            system_prompt=SUMMARY_SYSTEM_PROMPT,
        )
        return str(agent.run(prompt)).strip()

    def _remember_summary(self, conversation_id: str, covered: int, summary: str) -> None:
        self._summary_cache[conversation_id] = (covered, summary)
        self._summary_cache.move_to_end(conversation_id)
        while len(self._summary_cache) > 256:
            self._summary_cache.popitem(last=False)
