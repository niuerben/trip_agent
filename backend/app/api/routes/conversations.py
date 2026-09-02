"""统一聊天记录持久化接口。"""

import json
from typing import Any
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import jwt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from ...config import get_settings
from ...database import engine

router = APIRouter(prefix="/conversations", tags=["聊天记录"])
settings = get_settings()
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def as_beijing(value: datetime) -> str:
    """统一以北京时间(+08:00)输出时间。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING_TZ).isoformat()


class ConversationPayload(BaseModel):
    id: str = Field(..., max_length=100)
    title: str = Field(..., max_length=255)
    provider: str = Field(default="local", max_length=30)
    plan: dict[str, Any]
    createdAt: str
    updatedAt: str


def user_id_from_request(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        try:
            payload = jwt.decode(authorization[7:], settings.jwt_secret, algorithms=["HS256"])
            subject = payload.get("sub")
            if not subject:
                raise HTTPException(status_code=401, detail="JWT 缺少用户身份")
            return str(subject)
        except jwt.PyJWTError as error:
            raise HTTPException(status_code=401, detail="JWT 无效或已过期") from error
    return "local:guest"


def authenticated_user_id(request: Request) -> str:
    """返回已登录用户 ID；没有有效 Bearer JWT 时拒绝请求。"""
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    return user_id_from_request(request)


def parse_client_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING_TZ)
    return parsed


async def ensure_user(user_id: str) -> None:
    if engine is None:
        raise HTTPException(503, "DATABASE_URL未配置")
    async with engine.begin() as connection:
        await connection.execute(text("""
            INSERT INTO app_users (id, username, display_name)
            VALUES (:id, :username, :display_name)
            ON CONFLICT (id) DO NOTHING
        """), {"id": user_id, "username": user_id[:100], "display_name": user_id[:100]})


@router.get("")
async def list_conversations(request: Request):
    user_id = user_id_from_request(request)
    await ensure_user(user_id)
    async with engine.connect() as connection:
        result = await connection.execute(text("""
            SELECT id, title, provider, payload, created_at, updated_at
            FROM conversations WHERE user_id = :user_id ORDER BY updated_at DESC
        """), {"user_id": user_id})
        return [
            {"id": row.id, "title": row.title, "provider": row.provider,
             "plan": row.payload, "createdAt": as_beijing(row.created_at),
             "updatedAt": as_beijing(row.updated_at)}
            for row in result
        ]


@router.post("")
async def save_conversation(payload: ConversationPayload, request: Request):
    user_id = user_id_from_request(request)
    await ensure_user(user_id)
    async with engine.begin() as connection:
        await connection.execute(text("""
            INSERT INTO conversations (id, user_id, title, provider, payload, created_at, updated_at)
            VALUES (:id, :user_id, :title, :provider, CAST(:payload AS JSONB), CAST(:created_at AS TIMESTAMPTZ), CAST(:updated_at AS TIMESTAMPTZ))
            ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, provider = EXCLUDED.provider,
                payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at
        """), {"id": payload.id, "user_id": user_id, "title": payload.title,
               "provider": payload.provider, "payload": json.dumps(payload.plan, ensure_ascii=False),
               "created_at": parse_client_datetime(payload.createdAt),
               "updated_at": parse_client_datetime(payload.updatedAt)})
    return {"success": True, "id": payload.id}


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request):
    if engine is None:
        raise HTTPException(503, "DATABASE_URL未配置")
    print(conversation_id,user_id_from_request(request))
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM conversations WHERE id = :id AND user_id = :user_id"),
                                 {"id": conversation_id, "user_id": user_id_from_request(request)})
    return {"success": True}
