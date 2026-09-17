"""Talk 上下文窗口压缩测试：预算判定、滚动摘要、增量缓存与失败降级。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.models.schemas import TalkMessage, TalkRequest
from backend.app.services.context_compactor import ContextCompactor, estimate_tokens


def _request(
    messages: list[TalkMessage],
    conversation_id: str | None = "conv-1",
) -> TalkRequest:
    return TalkRequest(
        conversation_id=conversation_id,
        city="深圳",
        messages=messages,
        message="推荐路线",
    )


def _messages(count: int, content: str = "我喜欢大学校园和博物馆") -> list[TalkMessage]:
    return [
        TalkMessage(role="user" if index % 2 == 0 else "assistant", content=f"{content}-{index}")
        for index in range(count)
    ]


class ContextCompactorTest(unittest.TestCase):
    def test_under_budget_keeps_all_messages_without_summary(self) -> None:
        compactor = ContextCompactor(summarizer=lambda prompt: self.fail("预算内不应触发摘要"))

        lines, summary = compactor.compact_messages(_request(_messages(4)), history_budget=10_000)

        self.assertEqual(len(lines), 4)
        self.assertIsNone(summary)
        self.assertTrue(all(line.startswith(("用户:", "顾问:")) for line in lines))

    def test_over_budget_compacts_old_messages_into_summary(self) -> None:
        prompts: list[str] = []

        def fake_summarizer(prompt: str) -> str:
            prompts.append(prompt)
            return "旧对话要点：用户偏好校园与博物馆。"

        compactor = ContextCompactor(summarizer=fake_summarizer)
        # 每条约 30 字，20 条远超 200 字预算。
        lines, summary = compactor.compact_messages(
            _request(_messages(20)), history_budget=200
        )

        self.assertIsNotNone(summary)
        self.assertEqual(summary, "旧对话要点：用户偏好校园与博物馆。")
        self.assertTrue(lines[0].startswith("[更早对话摘要]"))
        self.assertIn(summary, lines[0])
        # 最近原文被保留，最旧的原文行不再出现。
        self.assertLessEqual(estimate_tokens("\n".join(lines)), 200)
        self.assertNotIn("我喜欢大学校园和博物馆-0", "\n".join(lines))
        self.assertTrue(any("我喜欢大学校园和博物馆-19" in line for line in lines))

    def test_rolling_summary_is_incremental_per_conversation(self) -> None:
        prompts: list[str] = []
        compactor = ContextCompactor(
            summarizer=lambda prompt: (prompts.append(prompt) or "合并后的摘要。")
        )

        first_lines, _ = compactor.compact_messages(
            _request(_messages(20, "第一批内容")), history_budget=200
        )
        self.assertTrue(first_lines[0].startswith("[更早对话摘要]"))
        first_call_count = len(prompts)

        second_lines, _ = compactor.compact_messages(
            _request(_messages(24, "第一批内容") + _messages(4, "第二批内容")), history_budget=200
        )
        self.assertTrue(second_lines[0].startswith("[更早对话摘要]"))
        # 增量摘要：第二次只新增一次 LLM 调用，且提示词携带已有摘要与新片段。
        self.assertEqual(len(prompts), first_call_count + 1)
        self.assertIn("合并后的摘要。", prompts[-1])

    def test_summarizer_failure_falls_back_to_truncation(self) -> None:
        def broken_summarizer(prompt: str) -> str:
            raise RuntimeError("LLM 不可用")

        compactor = ContextCompactor(summarizer=broken_summarizer)
        lines, summary = compactor.compact_messages(
            _request(_messages(20)), history_budget=200
        )

        self.assertIsNone(summary)
        self.assertTrue(all(not line.startswith("[更早对话摘要]") for line in lines))
        self.assertLessEqual(estimate_tokens("\n".join(lines)), 200)
        self.assertTrue(any("我喜欢大学校园和博物馆-19" in line for line in lines))

    def test_always_keeps_the_newest_message(self) -> None:
        compactor = ContextCompactor(summarizer=lambda prompt: "")
        lines, _ = compactor.compact_messages(_request(_messages(30)), history_budget=40)

        self.assertTrue(lines)
        self.assertIn("我喜欢大学校园和博物馆-29", lines[-1])


if __name__ == "__main__":
    from test._output import run_unittest

    run_unittest("验证上下文窗口压缩、滚动摘要与降级。")
