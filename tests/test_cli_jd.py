"""CLI-level tests for `jobagent jd`. The LLM is faked; no network, no cost.

The commands are thin, but the seams they cross — config to store to renderer —
are exactly where wiring mistakes hide.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from jobagent.adapters.llm import LLMError
from jobagent.cli import jd as jd_cli
from jobagent.cli.main import app
from jobagent.config import Config
from tests.test_jd import SAMPLE_TEXT, FakeClient

runner = CliRunner()


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point the CLI at a temp database and a fake model."""
    config = Config(_env_file=None, db_path=tmp_path / "jobagent.db")
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
