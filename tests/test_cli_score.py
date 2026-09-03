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
from jobagent.core.models import (
    Application,
    ApplicationStatus,
    JobDescription,
    WorkArrangement,
    WorkType,
    Worth,
)

runner = CliRunner()


def flat(output: str) -> str:
    """Collapse rich's wrapping, so an assertion is about the words printed
    and not about the width of the terminal the test happened to run in."""
    return " ".join(output.split())

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


# --------------------------------------------------------------------------- #
# Company history
# --------------------------------------------------------------------------- #


def add_nuix_rejection(config) -> None:
    """The real case: Nuix screened him out, then posted again the next day."""
    with store.open_store(config.db_path) as conn:
        jd = make_jd(WHOLE_AD)
        jd.title = "Engineering Manager - AI Team"
        jd.company = "Nuix"
        jd_id = store.add_jd(conn, jd)
        store.save_application(
            conn,
            Application(
                jd_id=jd_id,
                status=ApplicationStatus.rejected_screen,
                worth_applying=Worth.yes,
                worth_why="I fit the job description reasonably well.",
                updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            ),
        )


def add_second_nuix_ad(config) -> int:
    with store.open_store(config.db_path) as conn:
        jd = make_jd(WHOLE_AD)
        jd.title = "Principal Software Engineer - AI Team"
        jd.company = "Nuix"
        return store.add_jd(conn, jd)


def test_a_prior_rejection_is_shown_before_the_model_is_called(wired) -> None:
    add_nuix_rejection(wired)
    jd_id = add_second_nuix_ad(wired)

    result = runner.invoke(app, ["score", str(jd_id)])

    assert "Seen before" in flat(result.output)
    assert "Nuix" in flat(result.output)
    assert "rejected at screen" in flat(result.output)
    # Warn-only. The history reports; it does not decide.
    assert "does not change the verdict" in flat(result.output)


def test_history_is_shown_on_a_free_read_too(wired) -> None:
    add_nuix_rejection(wired)
    jd_id = add_second_nuix_ad(wired)

    result = runner.invoke(app, ["score", str(jd_id), "--last"])

    assert "Seen before" in result.output


def test_a_company_seen_once_says_nothing(wired) -> None:
    jd_id = add(wired, WHOLE_AD)

    result = runner.invoke(app, ["score", str(jd_id)])

    assert "Seen before" not in result.output
