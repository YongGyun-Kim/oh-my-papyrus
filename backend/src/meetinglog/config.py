from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from meetinglog.domain import Mode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEETINGLOG_", env_file=".env", extra="ignore", populate_by_name=True
    )

    data_dir: Path = Path("data")
    models_dir: Path = Path("models")
    max_upload_bytes: int = 2_000_000_000
    max_duration_ms: int = 7_200_000
    mode: Mode = "local_only"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gpt-oss:20b"
    openai_api_key: str | None = Field(
        default=None, validation_alias="OPENAI_API_KEY", exclude=True
    )
    openai_speech_model: str = "gpt-4o-transcribe-diarize"
    openai_analysis_model: str = "gpt-5-mini"
    asr_repo: str = "mlx-community/Qwen3-ASR-1.7B-8bit"
    aligner_repo: str = "mlx-community/Qwen3-ForcedAligner-0.6B-8bit"
    vad_repo: str = "mlx-community/silero-vad"
    diarizer_repo: str = "mlx-community/Nemotron-3-Diarization"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "meetinglog.sqlite3"

    @property
    def allowed_origins(self) -> list[str]:
        return [
            f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8765)
        ]
