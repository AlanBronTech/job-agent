"""CLI-level tests for `jobagent apply`. No network, no cost.

`--on` shipped calling a `_parse_date` that was never written, so every use of
the flag raised NameError and every row in the table had an empty
`applied_on`. The date is not decoration: outcomes.yaml grades a rejection
inside three days as automated and one after three weeks as human, and that
distinction is computed from this field.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from jobagent.cli import apply as apply_cli
from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import JobDescription, WorkArrangement, WorkType

runner = CliRunner()

NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    config = Config(
        _env_file=None,
        db_path=tmp_path / "jobagent.db",
        output_dir=tmp_path / "out",
    )
    monkeypatch.setattr(apply_cli, "get_config", lambda: config)
    return config


def seed(config) -> int:
    with store.open_store(config.db_path) as conn:
        return store.add_jd(
            conn,
            JobDescription(
                title="Senior Manager, AI Product Delivery Engineering",
                company="Colonial First State",
                work_type=WorkType.permanent,
                work_arrangement=WorkArrangement.hybrid,
                raw_text="We are hiring. " * 60,
                ingested_at=NOW,
            ),
        )


def stored(config, jd_id: int):
    with store.open_store(config.db_path) as conn:
        return store.get_application(conn, jd_id)


def test_an_explicit_date_is_recorded(wired) -> None:
    jd_id = seed(wired)

    result = runner.invoke(
        app, ["apply", str(jd_id), "--on", "2026-09-04", "--channel", "linkedin"]
    )

    assert result.exit_code == 0
    application = stored(wired, jd_id)
    assert application.applied_on == date(2026, 9, 4)
    assert application.channel == "linkedin"


def test_the_date_defaults_to_today(wired) -> None:
    jd_id = seed(wired)

    result = runner.invoke(app, ["apply", str(jd_id)])

    assert result.exit_code == 0
    assert stored(wired, jd_id).applied_on == date.today()


def test_an_unreadable_date_is_refused_without_writing(wired) -> None:
    jd_id = seed(wired)

    result = runner.invoke(app, ["apply", str(jd_id), "--on", "4 Sept"])

    assert result.exit_code == 2
    assert "Could not read" in result.output
    assert "YYYY-MM-DD" in result.output
    assert stored(wired, jd_id) is None


def test_a_future_date_is_refused(wired) -> None:
    """An application date records something that has already happened."""
    jd_id = seed(wired)
    tomorrow = date.today() + timedelta(days=1)

    result = runner.invoke(app, ["apply", str(jd_id), "--on", tomorrow.isoformat()])

    assert result.exit_code == 2
    assert "in the future" in result.output
    assert stored(wired, jd_id) is None


def test_today_is_not_treated_as_the_future(wired) -> None:
    jd_id = seed(wired)

    result = runner.invoke(app, ["apply", str(jd_id), "--on", date.today().isoformat()])

    assert result.exit_code == 0
    assert stored(wired, jd_id).applied_on == date.today()
