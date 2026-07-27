"""JWT会话与第三方OAuth入口。

微信网页登录和GitHub OAuth都需要在部署环境中配置客户端密钥；本模块只负责
服务端换取授权码、签发本应用JWT，不把第三方密钥暴露给浏览器。
"""
import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ...config import get_settings
from ...database import engine
from sqlalchemy import text

router = APIRouter(prefix="/auth", tags=["认证"])
settings = get_settings()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        actual = hash_password(password, salt).split("$", 1)[1]
        return secrets.compare_digest(actual, expected)
    except ValueError:
        return False


def create_token(user: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": user["id"], "name": user["name"], "avatar": user.get("avatar"), "exp": expire}, settings.jwt_secret, algorithm="HS256")


def frontend_redirect(token: str, redirect_uri: str, user: dict) -> RedirectResponse:
    target = redirect_uri or "http://localhost:5173"
    query = urlencode({"access_token": token, "user": user["name"]})
    return RedirectResponse(f"{target}/?{query}")


@router.post("/login")
async def password_login(payload: LoginRequest):
    """使用配置的账号密码签发JWT，适合本地/内部部署使用。"""
    if engine is not None:
        try:
            async def query_local_user():
                async with engine.connect() as connection:
                    result = await connection.execute(text("""
                        SELECT id, display_name, avatar, password_hash
                        FROM app_users WHERE username = :username AND provider = 'local'
                    """), {"username": payload.username})
                    return result.first()

            # 数据库不可达时仍允许本地 .env 账号登录，避免登录接口被连接池无限阻塞。
            user_row = await asyncio.wait_for(query_local_user(), timeout=3)
        except Exception as error:
            print(f"本地用户数据库查询失败，回退配置账号: {type(error).__name__}: {error}")
            user_row = None
        if user_row:
            if not user_row.password_hash or not verify_password(payload.password, user_row.password_hash):
                raise HTTPException(status_code=401, detail="用户名或密码错误")
            user = {"id": user_row.id, "name": user_row.display_name, "avatar": user_row.avatar}
            return {"access_token": create_token(user), "token_type": "bearer", "user": user}

    if payload.username != settings.auth_username or payload.password != settings.auth_password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user = {"id": f"local:{payload.username}", "name": payload.username}
    return {"access_token": create_token(user), "token_type": "bearer", "user": user}


@router.post("/register")
async def register(payload: LoginRequest):
    """注册本地账号并签发JWT。"""
    if engine is None:
        raise HTTPException(status_code=503, detail="数据库未连接，暂时无法注册")

    user_id = f"local:{payload.username}"
    password_hash = hash_password(payload.password)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("""
                INSERT INTO app_users (id, username, password_hash, display_name, provider)
                VALUES (:id, :username, :password_hash, :display_name, 'local')
            """), {"id": user_id, "username": payload.username,
                   "password_hash": password_hash, "display_name": payload.username})
    except Exception as error:
        if "unique" in str(error).lower() or "duplicate" in str(error).lower():
            raise HTTPException(status_code=409, detail="用户名已存在") from error
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试") from error

    user = {"id": user_id, "name": payload.username}
    return {"access_token": create_token(user), "token_type": "bearer", "user": user}


@router.get("/{provider}/start")
async def oauth_start(provider: str, redirect_uri: str = Query("http://localhost:5173")):
    if provider == "github":
        if not settings.github_client_id:
            raise HTTPException(503, "GitHub OAuth未配置")
        params = urlencode({"client_id": settings.github_client_id, "redirect_uri": settings.github_redirect_uri, "scope": "read:user user:email", "state": redirect_uri})
        return RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")
    if provider == "wechat":
        if not settings.wechat_app_id:
            raise HTTPException(503, "微信OAuth未配置")
        params = urlencode({"appid": settings.wechat_app_id, "redirect_uri": settings.wechat_redirect_uri, "response_type": "code", "scope": "snsapi_login", "state": redirect_uri})
        return RedirectResponse(f"https://open.weixin.qq.com/connect/qrconnect?{params}#wechat_redirect")
    raise HTTPException(404, "不支持的登录方式")


@router.get("/{provider}/callback")
async def oauth_callback(provider: str, code: str, state: str = "http://localhost:5173"):
    async with httpx.AsyncClient(timeout=15) as client:
        if provider == "github":
            token_response = await client.post("https://github.com/login/oauth/access_token", data={"client_id": settings.github_client_id, "client_secret": settings.github_client_secret, "code": code}, headers={"Accept": "application/json"})
            access_token = token_response.json().get("access_token")
            profile = (await client.get("https://api.github.com/user", headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"})).json()
            user = {"id": f"github:{profile['id']}", "name": profile.get("name") or profile.get("login", "GitHub用户"), "avatar": profile.get("avatar_url")}
        elif provider == "wechat":
            token_response = await client.get("https://api.weixin.qq.com/sns/oauth2/access_token", params={"appid": settings.wechat_app_id, "secret": settings.wechat_app_secret, "code": code, "grant_type": "authorization_code"})
            oauth = token_response.json()
            profile = (await client.get("https://api.weixin.qq.com/sns/userinfo", params={"access_token": oauth.get("access_token"), "openid": oauth.get("openid"), "lang": "zh_CN"})).json()
            user = {"id": f"wechat:{profile.get('openid')}", "name": profile.get("nickname", "微信用户"), "avatar": profile.get("headimgurl")}
        else:
            raise HTTPException(404, "不支持的登录方式")
    return frontend_redirect(create_token(user), state, user)


@router.get("/me")
async def me():
    return {"message": "请在客户端携带Authorization Bearer JWT后接入用户解析"}
