"""Application configuration using pydantic-settings"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os

# Get project root directory (where .env should be)
# Try multiple possible locations
def find_env_file() -> Optional[Path]:
    """Find .env file in project root"""
    # Current file is in src/config/config.py
    # So project root is 3 levels up
    project_root = Path(__file__).parent.parent.parent
    
    # Try project root first
    env_file = project_root / ".env"
    if env_file.exists():
        return env_file
    
    # Try current working directory
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env
    
    # Try parent of cwd
    parent_env = Path.cwd().parent / ".env"
    if parent_env.exists():
        return parent_env
    
    return None

ENV_FILE = find_env_file()
ENV_FILE_STR = str(ENV_FILE) if ENV_FILE else None


class MatrixConfig(BaseSettings):
    """Matrix configuration"""
    homeserver: str
    user_id: str
    access_token: str
    device_id: Optional[str] = None
    
    model_config = SettingsConfigDict(
        env_prefix="MATRIX_",
        env_file=ENV_FILE_STR,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class MinIOConfig(BaseSettings):
    """MinIO/S3 configuration for egress output"""
    endpoint: str  # MinIO endpoint URL (e.g., http://localhost:9000)
    access_key: str  # MinIO access key
    secret_key: str  # MinIO secret key
    bucket: str  # Bucket name for recordings
    region: str = "us-east-1"  # S3 region (default for MinIO)
    use_ssl: bool = False  # Whether to use SSL/TLS
    
    model_config = SettingsConfigDict(
        env_prefix="MINIO_",
        env_file=ENV_FILE_STR,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class LiveKitConfig(BaseSettings):
    """LiveKit configuration"""
    url: str
    api_key: str
    api_secret: str
    dev_mode: bool = False  # If True, automatically create rooms when calls start
    
    model_config = SettingsConfigDict(
        env_prefix="LIVEKIT_",
        env_file=ENV_FILE_STR,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Convert ws:// to http:// and wss:// to https:// for API usage
        if self.url.startswith("ws://"):
            import logging
            logging.warning(f"LiveKit URL starts with ws://, converting to http:// for API usage")
            self.url = self.url.replace("ws://", "http://", 1)
        elif self.url.startswith("wss://"):
            import logging
            logging.warning(f"LiveKit URL starts with wss://, converting to https:// for API usage")
            self.url = self.url.replace("wss://", "https://", 1)


class DatabaseConfig(BaseSettings):
    """Database configuration"""
    url: str
    
    model_config = SettingsConfigDict(
        env_prefix="DATABASE_",
        env_file=ENV_FILE_STR,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class ServerConfig(BaseSettings):
    """Server configuration"""
    host: str = "0.0.0.0"
    port: int = 8000
    
    model_config = SettingsConfigDict(
        env_prefix="SERVER_",
        env_file=ENV_FILE_STR,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class AppConfig:
    """Main application configuration - single source of truth
    
    This class aggregates all configuration sub-modules.
    Each sub-config is loaded independently from .env with its own prefix.
    """
    
    def __init__(self):
        """Initialize all configuration sub-modules"""
        self.matrix = MatrixConfig()
        self.livekit = LiveKitConfig()
        self.minio = MinIOConfig()
        self.database = DatabaseConfig()
        self.server = ServerConfig()
