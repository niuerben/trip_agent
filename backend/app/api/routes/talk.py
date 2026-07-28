"""偏好对话 API 路由。

与 talk_agent 多轮对话，收集用户旅行偏好；聊天消息按 conversation 持久化到
chat_messages 表（未配置 DATABASE_URL 时自动降级，仅返回回复不落库）。
"""

import asyncio

from fastapi import APIRouter, Request
from sqlalchemy import text

from ...agents.talk_agent import get_talk_agent
from ...config import get_settings
from ...database import engine
from ...models.schemas import (
    ChatHistoryResponse,
    ChatMessage,
    Preference,
    TalkMessage,
    TalkRequest,
    TalkResponse,
    TalkSuggestionsRequest,
    TalkSuggestionsResponse,
)
from .conversations import as_beijing, ensure_user, user_id_from_request

router = APIRouter(prefix="/talk", tags=["偏好对话"])
settings = get_settings()


async def _load_history(conversation_id: str, user_id: str | None = None) -> list[ChatMessage]:
    """读取某个行程对话的全部聊天记录（按时间升序）。"""
    if engine is None or not conversation_id:
        return []
    async with engine.connect() as connection:
        query = """
            SELECT id, conversation_id, role, content, created_at
            FROM chat_messages WHERE conversation_id = :conversation_id
        """
        params = {"conversation_id": conversation_id}
        if user_id:
            query += " AND user_id = :user_id"
            params["user_id"] = user_id
        query += " ORDER BY created_at ASC, id ASC"
        result = await connection.execute(text(query), params)
        return [
            ChatMessage(
                id=row.id,
                conversation_id=row.conversation_id,
                role=row.role,
                content=row.content,
                created_at=as_beijing(row.created_at),
            )
            for row in result
        ]


async def _load_conversation_preference(
    conversation_id: str,
    user_id: str,
) -> Preference | None:
    """读取当前用户在该会话中已持久化的长期偏好。"""
    if engine is None or not conversation_id:
        return None
    async with engine.connect() as connection:
        result = await connection.execute(text("""
            SELECT prompt FROM conversation_preferences
            WHERE conversation_id = :conversation_id AND user_id = :user_id
        """), {"conversation_id": conversation_id, "user_id": user_id})
        row = result.first()
    return Preference(prompt=row.prompt) if row and row.prompt else None


async def _persist_messages(
    conversation_id: str,
    user_id: str,
    pairs: list[tuple[str, str]],
) -> None:
    """把 (role, content) 消息写入 chat_messages。"""
    async with engine.begin() as connection:
        for role, content in pairs:
            await connection.execute(text("""
                INSERT INTO chat_messages (conversation_id, user_id, role, content)
                VALUES (:conversation_id, :user_id, :role, :content)
            """), {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "role": role,
                "content": content,
            })


@router.post(
    "",
    response_model=TalkResponse,
    summary="偏好对话",
    description="与偏好对话智能体多轮聊天，收集并提炼用户旅行偏好；聊天记录按 conversation 持久化",
)
async def talk(request: TalkRequest, http_request: Request) -> TalkResponse:
    """
    处理一轮偏好对话；模型不可用时返回安全兜底回复，不抛 500。
    """
    user_id = user_id_from_request(http_request)

    # 已落库的历史作为上下文来源；未配置数据库时退回到请求携带的 messages。
    history: list[ChatMessage] = []
    remembered_preference: Preference | None = None
    if request.conversation_id and engine is not None:
        try:
            await ensure_user(user_id)
            history = await _load_history(request.conversation_id, user_id)
            remembered_preference = await _load_conversation_preference(request.conversation_id, user_id)
        except Exception as error:
            print(f"加载聊天历史失败，忽略: {type(error).__name__}: {error}")

    context_messages = (
        [TalkMessage(role=m.role, content=m.content) for m in history]
        if history
        else list(request.messages)
    )
    agent_request = TalkRequest(
        conversation_id=request.conversation_id,
        city=request.city,
        plan_context=request.plan_context,
        preference=remembered_preference,
        messages=context_messages,
        message=request.message,
    )

    # 调用对话智能体（带超时；失败走兜底回复）。
    try:
        agent = await asyncio.wait_for(
            asyncio.to_thread(get_talk_agent),
            timeout=settings.planner_init_timeout_seconds,
        )
        result = await asyncio.wait_for(
            asyncio.to_thread(agent.chat, agent_request),
            timeout=settings.planner_execution_timeout_seconds,
        )
        reply = result.reply
        intent = result.intent
        change_request = result.change_request
        change_set = result.change_set
        top_suggestions = result.top_suggestions
        preference = result.preference
        done = result.done
        print(
            f"✅ 对话语义判定完成: intent={intent}; "
            f"change_request={repr(change_request or '无')}; "
            f"operations={len(change_set.operations) if change_set else 0}; "
            f"top_suggestions={len(top_suggestions)}"
        )
    except Exception as error:
        print(f"❌ 偏好对话服务不可用，使用兜底回复: {type(error).__name__}: {error}")
        reply = "好的，我已经记下你的偏好啦，可以直接开始规划行程～"
        preference = Preference(prompt=(request.message or "").strip())
        intent = "chat"
        change_request = None
        change_set = None
        top_suggestions = []
        done = True

    # 持久化用户消息与助手回复；失败不影响对话返回。
    messages: list[ChatMessage] = []
    if request.conversation_id and engine is not None:
        try:
            await _persist_messages(
                request.conversation_id,
                user_id,
                [("user", request.message), ("assistant", reply)],
            )
            messages = await _load_history(request.conversation_id, user_id)
        except Exception as error:
            print(f"聊天记录持久化失败，忽略: {type(error).__name__}: {error}")

    # 将 talk_agent 提炼出的偏好与当前行程对话关联，供后续 /trip/plan 使用。
    if request.conversation_id and preference and preference.prompt and engine is not None:
        try:
            async with engine.begin() as connection:
                await connection.execute(text("""
                    INSERT INTO conversation_preferences (conversation_id, user_id, prompt, updated_at)
                    VALUES (:conversation_id, :user_id, :prompt, NOW())
                    ON CONFLICT (conversation_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        prompt = EXCLUDED.prompt,
                        updated_at = NOW()
                """), {
                    "conversation_id": request.conversation_id,
                    "user_id": user_id,
                    "prompt": preference.prompt,
                })
        except Exception as error:
            print(f"偏好持久化失败，忽略: {type(error).__name__}: {error}")

    return TalkResponse(
        success=True,
        reply=reply,
        intent=intent,
        change_request=change_request,
        change_set=change_set,
        top_suggestions=top_suggestions,
        preference=preference,
        done=done,
        messages=messages,
    )


@router.get(
    "/{conversation_id}",
    response_model=ChatHistoryResponse,
    summary="获取聊天历史",
    description="返回某个行程对话的全部 AI 助手聊天记录",
)
async def get_chat_history(conversation_id: str, http_request: Request) -> ChatHistoryResponse:
    """读取聊天历史；未配置数据库时返回空列表。"""
    try:
        messages = await _load_history(conversation_id, user_id_from_request(http_request))
    except Exception as error:
        print(f"读取聊天历史失败: {type(error).__name__}: {error}")
        messages = []
    return ChatHistoryResponse(success=True, messages=messages)


@router.post(
    "/suggestions",
    response_model=TalkSuggestionsResponse,
    summary="恢复会话 Top3 建议",
    description="根据当前用户的已持久化会话记忆和行程摘要生成动态 Top3 建议，不写入聊天记录",
)
async def get_suggestions(
    request: TalkSuggestionsRequest,
    http_request: Request,
) -> TalkSuggestionsResponse:
    """在刷新页面或切换历史会话后恢复动态建议。"""
    user_id = user_id_from_request(http_request)
    try:
        history = await _load_history(request.conversation_id, user_id)
        preference = await _load_conversation_preference(request.conversation_id, user_id)
        agent = await asyncio.wait_for(
            asyncio.to_thread(get_talk_agent),
            timeout=settings.planner_init_timeout_seconds,
        )
        suggestions = await asyncio.wait_for(
            asyncio.to_thread(
                agent.generate_suggestions,
                TalkRequest(
                    conversation_id=request.conversation_id,
                    city=request.city,
                    plan_context=request.plan_context,
                    preference=preference,
                    messages=[TalkMessage(role=item.role, content=item.content) for item in history],
                    message="",
                ),
            ),
            timeout=settings.planner_execution_timeout_seconds,
        )
        return TalkSuggestionsResponse(success=True, top_suggestions=suggestions)
    except Exception as error:
        print(f"恢复 Top3 建议失败: {type(error).__name__}: {error}")
        return TalkSuggestionsResponse(success=False, top_suggestions=[])
