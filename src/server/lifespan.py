"""Application lifespan management"""
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from .db import async_session, init_db, close_db
from ..services.recording_service import RecordingService
from ..integrations.livekit_client import LiveKitClient
from ..integrations.matrix_bot import MatrixBot

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager"""
    # ---- Initialize Database ----
    await init_db()
    logger.info("Database initialized")
    
    # ---- DB session factory ----
    def session_factory() -> AsyncSession:
        return async_session()

    # ---- External integrations ----
    livekit_client = LiveKitClient()

    # ---- Application-level services ----
    recording_service = RecordingService(
        session_factory=session_factory,
        livekit_client=livekit_client,
    )
    
    # Initialize Matrix bot with dependencies
    matrix_bot = MatrixBot(
        livekit_client=livekit_client,
        recording_service=recording_service
    )

    # Save into app.state (dependency injection)
    app.state.session_factory = session_factory
    app.state.livekit_client = livekit_client
    app.state.matrix_bot = matrix_bot
    app.state.recording_service = recording_service

    # ---- Startup ----
    await matrix_bot.start()
    app.state.bot_task = asyncio.create_task(matrix_bot.run())

    logger.info("🚀 App startup complete")

    try:
        yield
    finally:
        # ---- Shutdown ----
        if hasattr(app.state, "bot_task"):
            app.state.bot_task.cancel()
            try:
                await app.state.bot_task
            except asyncio.CancelledError:
                logger.info("Bot stopped gracefully")

        await matrix_bot.stop()
        await close_db()
        logger.info("🛑 App shutdown complete")

