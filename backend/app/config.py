from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:8088"
    core_token: str = "development-only-change-me"
    core_timeout_seconds: float = 180.0
    max_audio_bytes: int = 25 * 1024 * 1024

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_prefix="JARVIS_", extra="ignore", case_sensitive=False
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
