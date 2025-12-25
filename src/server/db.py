"""Database configuration and session management"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import declarative_base
from typing import AsyncGenerator, Optional

from ..config.config import DatabaseConfig

# Base class for models
Base = declarative_base()

# Global engine - will be initialized in init_db
_engine: Optional[AsyncEngine] = None
_async_session: Optional[async_sessionmaker[AsyncSession]] = None


def init_db_engine(config: DatabaseConfig) -> None:
    """Initialize database engine with configuration"""
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
    """Get session factory - must be called after init_db_engine"""
    if _async_session is None:
        raise RuntimeError("Database not initialized. Call init_db_engine first.")
    return _async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting database session
    
    Yields:
        AsyncSession: Database session
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database (create tables)"""
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_db_engine first.")
    
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections"""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
