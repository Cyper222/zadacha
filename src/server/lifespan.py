"""Application lifespan management"""
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.config import AppConfig
from .db import init_db_engine, get_session_factory, init_db, close_db
from ..services.recording_service import RecordingService
from ..integrations.livekit_client import LiveKitClient
from ..integrations.matrix_bot import MatrixBot

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager"""
    # ---- Load configuration (single source of truth) ----
    try:
        config = AppConfig()
        logger.info("Configuration loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        logger.error("Please ensure .env file exists with all required variables")
        logger.error("See .env.example for reference")
        raise
    
    # Save config to app.state
    app.state.config = config
    
    # ---- Initialize Database ----
    init_db_engine(config.database)
    await init_db()
    logger.info("Database initialized")
    
    # ---- DB session factory ----
    def session_factory() -> AsyncSession:
        return get_session_factory()()
    
    app.state.session_factory = session_factory
    
    # ---- External integrations ----
    livekit_client = LiveKitClient(config.livekit, config.minio)
    app.state.livekit_client = livekit_client
    
    # ---- Application-level services ----
    recording_service = RecordingService(
        session_factory=session_factory,
        livekit_client=livekit_client,
    )
    app.state.recording_service = recording_service
    
    # Initialize Matrix bot with dependencies
    matrix_bot = MatrixBot(
        matrix_config=config.matrix,
        livekit_config=config.livekit,
        livekit_client=livekit_client,
        recording_service=recording_service
    )
    app.state.matrix_bot = matrix_bot

    # ---- Startup ----
    await matrix_bot.start()
    logger.info("Matrix bot initialized, starting sync task...")
    app.state.bot_task = asyncio.create_task(matrix_bot.run())
    logger.info(f"Bot sync task created: {app.state.bot_task}")

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
        
        # Close LiveKit client session
        if hasattr(app.state, "livekit_client"):
            await app.state.livekit_client.close()
        
        await close_db()
        logger.info("🛑 App shutdown complete")
