"""PostgreSQL连接与基础表初始化。"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .config import get_settings

settings = get_settings()
engine: AsyncEngine | None = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
) if settings.database_url else None


async def init_database() -> None:
    """创建应用所需的最小持久化表；后续可替换为 Alembic 迁移。"""
    if engine is None:
        print("⚠️ DATABASE_URL未配置，跳过PostgreSQL初始化")
        return

    async with engine.begin() as connection:
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS app_users (
                id VARCHAR(190) PRIMARY KEY,
                username VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(128),
                display_name VARCHAR(100) NOT NULL,
                provider VARCHAR(30) NOT NULL DEFAULT 'local',
                avatar TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS conversations (
                id VARCHAR(100) PRIMARY KEY,
                user_id VARCHAR(190) NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                provider VARCHAR(30) NOT NULL DEFAULT 'local',
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))


async def database_health() -> bool:
    if engine is None:
        return False
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
