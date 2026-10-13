from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VSA_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["local", "test"] = "local"
    data_dir: Path = PROJECT_ROOT / "data"
    llm_api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    llm_base_url: AnyHttpUrl | None = None
    llm_model: str | None = None
    asr_model: str = "small"
    asr_device: Literal["cpu", "cuda"] = "cpu"
    asr_compute_type: Literal["int8", "float16", "int8_float16"] = "int8"
    max_video_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    max_subtitle_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    max_duration_ms: int = Field(default=120 * 60 * 1000, gt=0)
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    @field_validator("data_dir")
    @classmethod
    def resolve_data_dir(cls, value: Path) -> Path:
        return (PROJECT_ROOT / value).resolve() if not value.is_absolute() else value.resolve()

    @field_validator("llm_base_url")
    @classmethod
    def reject_url_credentials(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value and (value.username or value.password):
            raise ValueError("Use the separate secret setting for credentials")
        return value
