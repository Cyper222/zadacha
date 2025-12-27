from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os


def find_env_file() -> Optional[Path]:
    project_root = Path(__file__).parent.parent.parent

    env_file = project_root / ".env"
    if env_file.exists():
        return env_file

    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env

    parent_env = Path.cwd().parent / ".env"
    if parent_env.exists():
        return parent_env
    
    return None

ENV_FILE = find_env_file()
ENV_FILE_STR = str(ENV_FILE) if ENV_FILE else None


class MatrixConfig(BaseSettings):
    homeserver: str
    user_id: str
    access_token: Optional[str] = None
    password: Optional[str] = None
    device_id: Optional[str] = None
    
    model_config = SettingsConfigDict(
        env_prefix="MATRIX_",
        env_file=ENV_FILE_STR,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Clean password: remove surrounding quotes if present (python-dotenv should handle this,
        # but we do it for safety, especially for passwords with special characters like #)
        if self.password:
            # Remove surrounding quotes (single or double) if they exist
            password = self.password.strip()
            if (password.startswith('"') and password.endswith('"')) or \
               (password.startswith("'") and password.endswith("'")):
                self.password = password[1:-1]
        
        # Validate that either access_token or password is provided
        if not self.access_token and not self.password:
            raise ValueError(
                "Either MATRIX_ACCESS_TOKEN or MATRIX_PASSWORD must be provided. "
                "Password is recommended for automatic token refresh."
            )


class MinIOConfig(BaseSettings):
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "us-east-1"
    use_ssl: bool = False
    
    model_config = SettingsConfigDict(
        env_prefix="MINIO_",
        env_file=ENV_FILE_STR,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class LiveKitConfig(BaseSettings):
    url: str
    api_key: str
    api_secret: str
    dev_mode: bool = False
    
    model_config = SettingsConfigDict(
        env_prefix="LIVEKIT_",
        env_file=ENV_FILE_STR,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.url.startswith("ws://"):
            self.url = self.url.replace("ws://", "http://", 1)
        elif self.url.startswith("wss://"):
            self.url = self.url.replace("wss://", "https://", 1)


class DatabaseConfig(BaseSettings):
    url: str
    
    model_config = SettingsConfigDict(
        env_prefix="DATABASE_",
        env_file=ENV_FILE_STR,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class ServerConfig(BaseSettings):
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
    
    def __init__(self):
        self.matrix = MatrixConfig()
        self.livekit = LiveKitConfig()
        self.minio = MinIOConfig()
        self.database = DatabaseConfig()
        self.server = ServerConfig()
