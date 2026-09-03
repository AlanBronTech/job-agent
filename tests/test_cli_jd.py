"""CLI-level tests for `jobagent jd`. The LLM is faked; no network, no cost.

The commands are thin, but the seams they cross — config to store to renderer —
are exactly where wiring mistakes hide.
"""

from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from jobagent.adapters.adtext import ExtractedAd
from jobagent.adapters.llm import LLMError
from jobagent.cli import jd as jd_cli
from jobagent.cli.main import app
from jobagent.config import Config
from tests.test_jd import SAMPLE_TEXT, FakeClient

runner = CliRunner()


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point the CLI at a temp database, a temp drop folder and a fake model."""
    drop = tmp_path / "jds"
    drop.mkdir()
    config = Config(
        _env_file=None, db_path=tmp_path / "jobagent.db", jd_dir=drop
    )
    monkeypatch.setattr(jd_cli, "get_config", lambda: config)

    client = FakeClient()
    monkeypatch.setattr(jd_cli, "get_client", lambda *args, **kwargs: client)
    return client


@pytest.fixture
def jd_file(tmp_path):
    path = tmp_path / "jd.txt"
    path.write_text(SAMPLE_TEXT, encoding="utf-8")
    return path


def test_add_from_file_saves_and_renders(wired, jd_file) -> None:
    result = runner.invoke(app, ["jd", "add", "--file", str(jd_file)])

    assert result.exit_code == 0, result.output
    assert "Engineering Manager" in result.output
    assert "Saved as JD 1" in result.output


def test_add_from_stdin(wired) -> None:
    result = runner.invoke(app, ["jd", "add", "--stdin"], input=SAMPLE_TEXT)

    assert result.exit_code == 0, result.output
    assert "Saved as JD 1" in result.output


def test_add_records_the_source(wired, jd_file) -> None:
    runner.invoke(app, ["jd", "add", "--file", str(jd_file), "--source", "seek"])
    result = runner.invoke(app, ["jd", "show", "1"])

    assert "seek" in result.output


def test_file_and_stdin_together_is_rejected(wired, jd_file) -> None:
    result = runner.invoke(app, ["jd", "add", "--file", str(jd_file), "--stdin"])

    assert result.exit_code == 2
    assert "not both" in result.output


def test_missing_file_fails_cleanly(wired, tmp_path) -> None:
    result = runner.invoke(app, ["jd", "add", "--file", str(tmp_path / "nope.txt")])

    assert result.exit_code == 2
    assert "Traceback" not in result.output


def test_unroutable_model_explains_itself(tmp_path, monkeypatch) -> None:
    config = Config(_env_file=None, db_path=tmp_path / "jobagent.db")
    monkeypatch.setattr(jd_cli, "get_config", lambda: config)

    def boom(*args, **kwargs):
        raise LLMError("No model configured for call type 'parse_jd'")

    monkeypatch.setattr(jd_cli, "get_client", boom)
    result = runner.invoke(app, ["jd", "add", "--stdin"], input=SAMPLE_TEXT)

    assert result.exit_code == 2
    assert "config check" in result.output


def test_list_is_helpful_when_empty(wired) -> None:
    result = runner.invoke(app, ["jd", "list"])

    assert result.exit_code == 0
    assert "No job descriptions yet" in result.output


def test_list_shows_added_jds(wired, jd_file) -> None:
    runner.invoke(app, ["jd", "add", "--file", str(jd_file)])
    result = runner.invoke(app, ["jd", "list"])

    assert result.exit_code == 0
    assert "Engineering Manager" in result.output
    assert "Acme" in result.output


def test_show_renders_requirements(wired, jd_file) -> None:
    runner.invoke(app, ["jd", "add", "--file", str(jd_file)])
    result = runner.invoke(app, ["jd", "show", "1"])

    assert result.exit_code == 0
    assert "Must haves" in result.output
    assert "Team leadership" in result.output


def test_show_unknown_id_exits_nonzero(wired) -> None:
    result = runner.invoke(app, ["jd", "show", "42"])

    assert result.exit_code == 1
    assert "No job description with id 42" in result.output


# --------------------------------------------------------------------------- #
# Naming the file. The saved ads have spaces and parentheses in their names,
# so anything that requires typing one exactly gets typed wrong.
# --------------------------------------------------------------------------- #


@pytest.fixture
def drop_folder(tmp_path):
    """The drop folder the `wired` config points at."""
    return tmp_path / "jds"


def _save_ad(drop_folder, name: str, mtime: float | None = None):
    path = drop_folder / name
    path.write_text(SAMPLE_TEXT, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_add_expands_a_tilde_path(wired, jd_file, monkeypatch) -> None:
    """zsh leaves `~` alone inside quotes; the CLI has to expand it itself."""
    monkeypatch.setenv("HOME", str(jd_file.parent))

    result = runner.invoke(app, ["jd", "add", "--file", f"~/{jd_file.name}"])

    assert result.exit_code == 0, result.output
    assert "Saved as JD 1" in result.output


def test_add_matches_a_fragment_of_a_saved_name(wired, drop_folder) -> None:
    _save_ad(drop_folder, "Engineering Manager (L5_L6) _ Ebury _ LinkedIn.txt")

    result = runner.invoke(app, ["jd", "add", "--file", "ebury"])

    assert result.exit_code == 0, result.output
    assert "Ebury" in result.output
    assert "Saved as JD 1" in result.output


def test_an_ambiguous_fragment_is_an_error_not_a_guess(wired, drop_folder) -> None:
    _save_ad(drop_folder, "Engineering Manager _ Xero.txt")
    _save_ad(drop_folder, "Engineering Manager _ Ebury.txt")

    result = runner.invoke(app, ["jd", "add", "--file", "Engineering Manager"])

    assert result.exit_code == 2
    assert "Xero" in result.output and "Ebury" in result.output


def test_an_existing_path_wins_over_fragment_matching(wired, drop_folder, jd_file) -> None:
    """A real path is never reinterpreted as a fragment."""
    _save_ad(drop_folder, f"decoy {jd_file.name}")

    result = runner.invoke(app, ["jd", "add", "--file", str(jd_file)])

    assert result.exit_code == 0, result.output
    assert "decoy" not in result.output


def test_a_fragment_matching_nothing_says_so(wired, drop_folder) -> None:
    result = runner.invoke(app, ["jd", "add", "--file", "atlassian"])

    assert result.exit_code == 2
    assert "atlassian" in result.output


def test_latest_takes_the_most_recently_saved_ad(wired, drop_folder) -> None:
    _save_ad(drop_folder, "old _ Xero.txt", mtime=1_000_000)
    _save_ad(drop_folder, "new _ Ebury.txt", mtime=2_000_000)

    result = runner.invoke(app, ["jd", "add", "--latest"])

    assert result.exit_code == 0, result.output
    assert "new _ Ebury.txt" in result.output


def test_latest_ignores_the_folder_furniture(wired, drop_folder) -> None:
    """The README and outcomes.yaml live in the drop folder and are not ads."""
    _save_ad(drop_folder, "ad _ Ebury.txt", mtime=1_000_000)
    (drop_folder / "outcomes.yaml").write_text("- {}\n", encoding="utf-8")
    os.utime(drop_folder / "outcomes.yaml", (2_000_000, 2_000_000))

    result = runner.invoke(app, ["jd", "add", "--latest"])

    assert result.exit_code == 0, result.output
    assert "ad _ Ebury.txt" in result.output


def test_latest_with_an_empty_drop_folder_says_so(wired, drop_folder) -> None:
    result = runner.invoke(app, ["jd", "add", "--latest"])

    assert result.exit_code == 2
    assert "No saved ad" in result.output


def test_file_and_latest_together_is_an_error(wired, drop_folder) -> None:
    _save_ad(drop_folder, "ad _ Ebury.txt")

    result = runner.invoke(app, ["jd", "add", "--file", "ebury", "--latest"])

    assert result.exit_code == 2
    assert "not both" in result.output


def test_a_thin_capture_warns_but_still_ingests(wired, jd_file, monkeypatch) -> None:
    """A collapsed description is worth flagging before $0.20 is spent scoring
    it, but a genuine two-sentence agency stub is still worth recording."""
    stub = ExtractedAd(
        text=SAMPLE_TEXT[:400],
        full_text=SAMPLE_TEXT,
        source_url="https://example.invalid/jobs/1",
        page_title=None,
        posting_metadata=None,
    )
    monkeypatch.setattr(jd_cli, "_extract_saved_page", lambda file: stub)

    result = runner.invoke(app, ["jd", "add", "--file", str(jd_file)])

    assert result.exit_code == 0, result.output
    assert "collapsed description" in result.output
    assert "Saved as JD 1" in result.output


# --------------------------------------------------------------------------- #
# Company history
# --------------------------------------------------------------------------- #


def test_the_second_ad_from_a_company_says_so(wired, jd_file) -> None:
    """The Nuix case: an ad from a company already in the pipeline must say so
    while the JD id is still on screen, before $0.20 is spent scoring it."""
    runner.invoke(app, ["jd", "add", "--file", str(jd_file)])

    result = runner.invoke(app, ["jd", "add", "--file", str(jd_file)])

    output = " ".join(result.output.split())
    assert result.exit_code == 0, result.output
    assert "Seen before — Acme Pty Ltd" in output
    assert "JD 1" in output
    assert "does not change the verdict" in output


def test_the_first_ad_from_a_company_says_nothing(wired, jd_file) -> None:
    result = runner.invoke(app, ["jd", "add", "--file", str(jd_file)])

    assert "Seen before" not in result.output
