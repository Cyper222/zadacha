from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class MatrixConfig(BaseSettings):
    homeserver: str
    user_id: str
    access_token: str
    device_id: Optional[str] = None
    
    model_config = SettingsConfigDict(
        env_prefix="MATRIX_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


class LiveKitConfig(BaseSettings):
    url: str
    api_key: str
    api_secret: str
    
    model_config = SettingsConfigDict(
        env_prefix="LIVEKIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


class BotConfig(BaseSettings):
    matrix: MatrixConfig
    livekit: LiveKitConfig
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

