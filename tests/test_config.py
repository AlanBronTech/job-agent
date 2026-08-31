"""Unit tests for runtime configuration.

The regression these guard against: an unset or unfound PROFILE_DIR used to
fall back to a hardcoded ~/.job-agent/profile, so a misconfigured run
validated a stale copy of the profile and reported success.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.cli import config as config_cli
from jobagent.cli import profile as profile_cli
from jobagent.cli.main import app as cli_app
from jobagent.config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# env_file anchoring
# --------------------------------------------------------------------------- #


def test_env_file_is_absolute_and_at_repo_root() -> None:
    env_file = Path(Config.model_config["env_file"])

    assert env_file.is_absolute()
    assert env_file == REPO_ROOT / ".env"


def test_stray_env_file_in_cwd_is_ignored(tmp_path: Path, monkeypatch) -> None:
    # A relative env_file would resolve against cwd and let this decoy win.
    decoy = tmp_path / ".env"
    decoy.write_text("PROFILE_DIR=/decoy/profile\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROFILE_DIR", raising=False)

    assert Config().profile_dir != Path("/decoy/profile")


# --------------------------------------------------------------------------- #
# No filesystem defaults
# --------------------------------------------------------------------------- #


def test_profile_dir_is_not_defaulted(monkeypatch) -> None:
    monkeypatch.delenv("PROFILE_DIR", raising=False)

    assert Config(_env_file=None).profile_dir is None


def test_profile_dir_expands_user(monkeypatch) -> None:
    monkeypatch.setenv("PROFILE_DIR", "~/elsewhere/profile")

    assert Config(_env_file=None).profile_dir == Path.home() / "elsewhere/profile"


# --------------------------------------------------------------------------- #
# The CLI must fail loudly rather than guess
# --------------------------------------------------------------------------- #


@pytest.fixture
def unset_profile_dir(monkeypatch):
    monkeypatch.delenv("PROFILE_DIR", raising=False)
    monkeypatch.setattr(profile_cli, "get_config", lambda: Config(_env_file=None))


def test_validate_without_profile_dir_exits_nonzero(unset_profile_dir) -> None:
    result = CliRunner().invoke(cli_app, ["profile", "validate"])

    assert result.exit_code == 2
    assert "PROFILE_DIR" in result.output


def test_explicit_dir_still_works_without_config(
    unset_profile_dir, example_dir: Path
) -> None:
    result = CliRunner().invoke(
        cli_app, ["profile", "validate", "--dir", str(example_dir)]
    )

    assert result.exit_code == 0
    assert "Profile OK" in result.output


# --------------------------------------------------------------------------- #
# `config check` must not report a placeholder as a working key
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "placeholder", ["sk-ant-...", "your-key-here", "...", "AIza..."]
)
def test_placeholder_keys_are_not_usable(placeholder: str) -> None:
    assert config_cli._is_usable(placeholder) is False


@pytest.mark.parametrize("secret", [None, ""])
def test_absent_keys_are_not_usable(secret) -> None:
    assert config_cli._is_usable(secret) is False


def test_a_realistic_key_is_usable() -> None:
    assert config_cli._is_usable("sk-ant-api03-" + "a" * 90) is True


def test_check_flags_a_placeholder_rather_than_reporting_ready(monkeypatch) -> None:
    config = Config(
        _env_file=None,
        anthropic_api_key="sk-ant-...",
        llm_default="anthropic:claude-sonnet-4-6",
    )
    monkeypatch.setattr(config_cli, "get_config", lambda: config)

    result = CliRunner().invoke(cli_app, ["config", "check"])

    assert result.exit_code == 0
    assert "placeholder" in result.output
    assert "Not ready" in result.output
    assert "All call types are routed and keyed" not in result.output


def test_check_reports_ready_with_a_real_looking_key(monkeypatch) -> None:
    config = Config(
        _env_file=None,
        gemini_api_key="AIza" + "b" * 35,
        llm_default="gemini:gemini-2.5-flash",
    )
    monkeypatch.setattr(config_cli, "get_config", lambda: config)

    result = CliRunner().invoke(cli_app, ["config", "check"])

    assert result.exit_code == 0
    assert "All call types are routed and keyed" in result.output


def test_check_never_prints_the_whole_key(monkeypatch) -> None:
    secret = "sk-ant-api03-" + "z" * 90
    config = Config(
        _env_file=None,
        anthropic_api_key=secret,
        llm_default="anthropic:claude-sonnet-4-6",
    )
    monkeypatch.setattr(config_cli, "get_config", lambda: config)

    result = CliRunner().invoke(cli_app, ["config", "check"])

    assert secret not in result.output


def test_runs_log_path_is_anchored_not_relative() -> None:
    # A bare "runs.jsonl" would scatter the eval harness's cost history across
    # whatever directory the CLI was run from.
    assert Config(_env_file=None).runs_log_path.is_absolute()
