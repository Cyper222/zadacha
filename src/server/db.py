from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import declarative_base
from typing import AsyncGenerator, Optional

from ..config.config import DatabaseConfig


Base = declarative_base()
_engine: Optional[AsyncEngine] = None
_async_session: Optional[async_sessionmaker[AsyncSession]] = None


def init_db_engine(config: DatabaseConfig) -> None:
    global _engine, _async_session
    
    _engine = create_async_engine(
        config.url,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )
    
    _async_session = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _async_session is None:
        raise RuntimeError("Database not initialized. Call init_db_engine first.")
    return _async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_db_engine first.")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
