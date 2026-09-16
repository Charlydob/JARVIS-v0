from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    gateway_ws_url: str = "ws://localhost:8000/internal/core/ws"
    core_token: str = "development-only-change-me"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    tts_voice: str = "es-ES-AlvaroNeural"
    data_dir: Path = Path.home() / ".jarvis"
    reconnect_max_seconds: int = 30
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_prefix="JARVIS_", extra="ignore", case_sensitive=False
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "memory.db"
