from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def detected_build_sha() -> str:
    root = Path(__file__).resolve().parents[2]
    git_marker = root / ".git"
    try:
        git_dir = git_marker
        if git_marker.is_file():
            git_dir = (root / git_marker.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip()).resolve()
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            head = (git_dir / head[5:]).read_text(encoding="utf-8").strip()
        return head
    except (OSError, IndexError):
        return "development"


class CoreSettings(BaseSettings):
    gateway_ws_url: str = "ws://localhost:8000/internal/core/ws"
    core_token: str = "development-only-change-me"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    tts_voice: str = "es-ES-AlvaroNeural"
    tool_modules: str = ""
    data_dir: Path = Path.home() / ".jarvis"
    reconnect_max_seconds: int = 30
    log_level: str = "INFO"
    build_sha: str = detected_build_sha()

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_prefix="JARVIS_", extra="ignore", case_sensitive=False
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "memory.db"
