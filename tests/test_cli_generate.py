"""CLI-level tests for `jobagent generate`. No network, no cost.

Only the guards that run before the model: this is the $0.30 command and the
day of work behind it, so what it says before spending is worth a test.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from jobagent.cli import generate as generate_cli
from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import (
    Application,
    ApplicationStatus,
    FitAssessment,
    JobDescription,
    Verdict,
    WorkArrangement,
    WorkType,
    Worth,
)

runner = CliRunner()

NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    config = Config(
        _env_file=None,
        db_path=tmp_path / "jobagent.db",
        output_dir=tmp_path / "out",
    )
    monkeypatch.setattr(generate_cli, "get_config", lambda: config)
    return config


def make_jd(title: str) -> JobDescription:
    return JobDescription(
        title=title,
        company="Nuix",
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        raw_text="We are hiring. " * 60,
        ingested_at=NOW,
    )


def seed(config) -> int:
    """A rejection at Nuix, then a second Nuix ad the scorer says skip to."""
    with store.open_store(config.db_path) as conn:
        first = store.add_jd(conn, make_jd("Engineering Manager - AI Team"))
        store.save_application(
            conn,
            Application(
                jd_id=first,
                status=ApplicationStatus.rejected_screen,
                worth_applying=Worth.yes,
                worth_why="I fit the job description reasonably well.",
                updated_at=NOW,
            ),
        )
        second = store.add_jd(conn, make_jd("Principal Software Engineer - AI Team"))
        store.add_assessment(
            conn,
            FitAssessment(
                jd_id=second,
                overall_score=40,
                recruiter_screen_score=40,
                verdict=Verdict.skip,
                rationale="Not the right shape.",
                target_role_match=False,
                target_role_note="Principal IC, not management.",
                scored_at=NOW,
            ),
        )
        return second


def test_the_company_history_is_shown_before_a_day_is_spent(wired) -> None:
    jd_id = seed(wired)

    result = runner.invoke(app, ["generate", str(jd_id), "--resume"])

    output = " ".join(result.output.split())
    assert "Seen before — Nuix" in output
    assert "rejected at screen" in output
    # The skip guard still does the stopping. History reports, it does not veto.
    assert result.exit_code == 2
    assert "The assessment says skip" in output


def test_nothing_is_said_for_an_unscored_ad(wired) -> None:
    """It has to be scored before it can be generated, and `score` has already
    printed the history by then."""
    with store.open_store(wired.db_path) as conn:
        jd_id = store.add_jd(conn, make_jd("Engineering Manager - AI Team"))

    result = runner.invoke(app, ["generate", str(jd_id), "--resume"])

    assert result.exit_code == 2
    assert "has not been scored" in result.output
