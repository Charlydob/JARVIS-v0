from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "JARVIS Core"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173"
    llm_provider: str = "mock"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_prefix="JARVIS_", extra="ignore", case_sensitive=False
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
