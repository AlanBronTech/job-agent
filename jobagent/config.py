"""Runtime configuration, read from environment / .env.

This is infrastructure, not business logic. `core/` never imports it — core
functions take the values they need as arguments so they stay callable from a
web handler or a test without touching the environment.

Every field is optional so that commands which need no secrets (notably
`profile validate`) run without a fully populated .env. Commands that need a
specific value (an API key, a Drive folder) validate its presence at their own
call site and fail with a clear message there.

Nothing here is *defaulted* to a filesystem path. A default that silently
points somewhere plausible is worse than no value: it turns a misconfiguration
into a command that succeeds against the wrong data. `profile_dir` in
particular was defaulted to ~/.job-agent/profile, which meant an unset
PROFILE_DIR quietly validated a stale copy instead of the real one.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings resolves a relative env_file against the *current working
# directory*, so `jobagent` run from anywhere but the repo root would find no
# .env at all and fall back to defaults without saying so. Anchor it instead.
_REPO_ROOT = Path(__file__).resolve().parents[1]


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    anthropic_api_key: str | None = None
    # Required only for identity-linked Anthropic keys, which are rejected
    # without an anthropic-workspace-id header. Workspace-scoped keys ignore it.
    anthropic_workspace_id: str | None = None
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

    # Budget mode: route every call to a model on a free tier, overriding the
    # per-call routing above. For when the API bill matters more than the
    # answer quality — which it sometimes does, and the eval harness can say
    # by how much rather than leaving it to a guess.
    budget_mode: bool = False
    budget_model: str = "gemini:gemini-2.5-flash"

    # Legacy fallbacks, still honoured when the llm_* routes are unset.
    anthropic_model: str | None = None
    anthropic_triage_model: str | None = None

    # Anchored, not relative. A bare "runs.jsonl" resolves against the current
    # working directory, so the eval harness's cost/token history would scatter
    # across whatever directories the CLI happened to be run from.
    runs_log_path: Path = Field(default=_REPO_ROOT / "runs.jsonl")

    profile_dir: Path | None = None

    # The drop folder Alan saves job ads into. Defaulted, unlike profile_dir,
    # because a wrong value here cannot silently succeed: `jd add` either
    # finds the named ad or says it did not.
    jd_dir: Path = Field(default=Path("~/job-agent-jds"))

    # Where generated documents are written, one folder per application.
    # Google Drive upload was dropped on 2026-09-01 in favour of a local
    # folder Alan copies from when it suits him; see BUILD_PLAN.md.
    output_dir: Path = Field(default=Path("~/job-agent-out"))

    db_path: Path = Field(default=Path("~/.job-agent/jobagent.db"))

    @field_validator(
        "profile_dir", "db_path", "runs_log_path", "output_dir", "jd_dir", mode="after"
    )
    @classmethod
    def _expand_user(cls, value: Path | None) -> Path | None:
        return None if value is None else Path(value).expanduser()


@lru_cache
def get_config() -> Config:
    """Return the process-wide config, loaded once."""
    return Config()