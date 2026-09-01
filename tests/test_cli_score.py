"""CLI-level tests for `jobagent score`. No network, no cost.

What is under test is the refusal, not the scoring: a capture too short to
draw conclusions from must not reach the model, because the model will draw
them anyway. JD 23 held 565 characters and came back with five assessed
requirements the ad never stated.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from jobagent.cli import score as score_cli
from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import JobDescription, WorkArrangement, WorkType

runner = CliRunner()

STUB = "Design and implement enterprise-scale AI solutions for clients. " * 6
WHOLE_AD = "We are hiring an Engineering Manager. " * 40


def make_jd(raw_text: str) -> JobDescription:
    return JobDescription(
        title="Digital Engineering Lead",
        company="Mattox Solution",
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.unknown,
        raw_text=raw_text,
        ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A temp database and no profile, so nothing can reach a model."""
    config = Config(_env_file=None, db_path=tmp_path / "jobagent.db")
    monkeypatch.setattr(score_cli, "get_config", lambda: config)
    return config


def add(config, raw_text: str) -> int:
    with store.open_store(config.db_path) as conn:
        return store.add_jd(conn, make_jd(raw_text))


def test_a_stub_ad_is_refused_before_it_costs_anything(wired) -> None:
    jd_id = add(wired, STUB)

    result = runner.invoke(app, ["score", str(jd_id)])

    assert result.exit_code == 2
    assert "too little to score" in result.output
    assert "--force" in result.output


def test_force_gets_past_the_refusal(wired) -> None:
    """--force must reach the normal path — here the missing profile — rather
    than being stopped by the length guard."""
    jd_id = add(wired, STUB)

    result = runner.invoke(app, ["score", str(jd_id), "--force"])

    assert "too little to score" not in result.output
    assert "No profile directory" in result.output


def test_a_whole_ad_is_never_refused(wired) -> None:
    jd_id = add(wired, WHOLE_AD)

    result = runner.invoke(app, ["score", str(jd_id)])

    assert "too little to score" not in result.output


def test_last_still_reads_a_stored_assessment_for_a_stub(wired) -> None:
    """The guard must not block a free read of what was already scored."""
    jd_id = add(wired, STUB)

    result = runner.invoke(app, ["score", str(jd_id), "--last"])

    assert "too little to score" not in result.output
    assert "has not been scored yet" in result.output
