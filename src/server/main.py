"""FastAPI server main entry point"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .lifespan import lifespan
from .routes.webhook_livekit import router as webhook_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="Matrix LiveKit Bot API",
    description="Backend API for Matrix LiveKit Bot",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)


@app.get("/")
async def root():
    return {
        "service": "matrix-livekit-bot",
        "version": "0.1.0",
        "status": "running"
    }
