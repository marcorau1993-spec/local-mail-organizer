"""Validated application settings with safe defaults."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Destructive behavior cannot be enabled in version 1."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_vision_model: str = "qwen2.5vl:7b"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8765, ge=1024, le=65535)
    dry_run: bool = True
    mail_provider: str = "webde"
    archive_root: Path | None = None
    large_message_bytes: int = Field(default=10 * 1024 * 1024, ge=1024 * 1024)
    scan_limit: int = Field(default=500, ge=1, le=5000)
    web_origin: str = "http://localhost:3000"
    database_path: Path = Path("data/local-mail-organizer.sqlite3")
    full_scan_batch_size: int = Field(default=100, ge=10, le=500)
    automation_interval_seconds: int = Field(default=300, ge=60, le=86400)
    automation_batch_size: int = Field(default=25, ge=1, le=100)
    content_index_max_message_bytes: int = Field(
        default=2 * 1024 * 1024, ge=64 * 1024, le=25 * 1024 * 1024
    )
    content_index_body_chars: int = Field(default=30_000, ge=1000, le=200_000)

    @property
    def destructive_actions_allowed(self) -> bool:
        """Version 1 is hard-locked to non-destructive operation."""
        return False
