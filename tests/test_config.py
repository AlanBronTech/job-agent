"""Unit tests for runtime configuration.

The regression these guard against: an unset or unfound PROFILE_DIR used to
fall back to a hardcoded ~/.job-agent/profile, so a misconfigured run
validated a stale copy of the profile and reported success.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

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
