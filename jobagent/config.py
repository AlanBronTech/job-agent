"""Runtime configuration, read from environment / .env.

This is infrastructure, not business logic. `core/` never imports it — core
functions take the values they need as arguments so they stay callable from a
web handler or a test without touching the environment.

Every field is optional or defaulted so that commands which need no secrets
(notably `profile validate`) run without a fully populated .env. Commands that
need a specific value (an API key, a Drive folder) validate its presence at
their own call site and fail with a clear message there.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None

    # Per-call-type routing. Each is a "provider:model" string; see
    # adapters/llm.py:resolve_route for the resolution order. Left unset,
    # they fall through to LLM_DEFAULT and then the legacy anthropic_* models.
    llm_default: str | None = None
    llm_triage: str | None = None
    llm_parse: str | None = None
    llm_score: str | None = None
    llm_generate: str | None = None
    llm_prep: str | None = None

    # Legacy fallbacks, still honoured when the llm_* routes are unset.
    anthropic_model: str | None = None
    anthropic_triage_model: str | None = None

    runs_log_path: Path = Field(default=Path("runs.jsonl"))

    profile_dir: Path = Field(default=Path("~/.job-agent/profile"))
    drive_resume_folder_id: str | None = None
    drive_coverletter_folder_id: str | None = None
    db_path: Path = Field(default=Path("~/.job-agent/jobagent.db"))

    @field_validator("profile_dir", "db_path", "runs_log_path", mode="after")
    @classmethod
    def _expand_user(cls, value: Path) -> Path:
        return Path(value).expanduser()


@lru_cache
def get_config() -> Config:
    """Return the process-wide config, loaded once."""
    return Config()