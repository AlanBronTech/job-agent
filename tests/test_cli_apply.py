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


# --------------------------------------------------------------------------- #
# A repost supersedes the age implied by the saved page
# --------------------------------------------------------------------------- #


def test_a_repost_date_is_recorded(wired) -> None:
    """Ebury's page was captured reading "3 weeks ago · 46 applicants", then
    reposted, then applied to the next day. Age at application was about zero
    days; the capture line implies twenty-four. Deriving from the capture alone
    is the same error as reading an applicant count off a page saved later."""
    jd_id = seed(wired)

    result = runner.invoke(
        app,
        ["apply", str(jd_id), "--on", "2026-09-02", "--reposted-on", "2026-09-02"],
    )

    assert result.exit_code == 0
    assert stored(wired, jd_id).reposted_on == date(2026, 9, 2)


def test_no_repost_leaves_the_field_empty(wired) -> None:
    """Absent is a real answer: most ads were never reposted."""
    jd_id = seed(wired)

    runner.invoke(app, ["apply", str(jd_id), "--on", "2026-09-04"])

    assert stored(wired, jd_id).reposted_on is None


def test_a_repost_after_the_application_is_refused(wired) -> None:
    """A repost Alan saw when he applied cannot postdate the application."""
    jd_id = seed(wired)

    result = runner.invoke(
        app,
        ["apply", str(jd_id), "--on", "2026-09-02", "--reposted-on", "2026-09-05"],
    )

    assert result.exit_code == 2
    assert "after the application" in result.output
    assert stored(wired, jd_id) is None


def test_the_repost_date_survives_a_later_status_change(wired) -> None:
    """`outcome` must not drop it — it is the input to ad age at application."""
    jd_id = seed(wired)
    runner.invoke(
        app,
        ["apply", str(jd_id), "--on", "2026-09-02", "--reposted-on", "2026-09-02"],
    )

    runner.invoke(app, ["outcome", str(jd_id), "rejected_screen", "--worth", "no"])

    assert stored(wired, jd_id).reposted_on == date(2026, 9, 2)


# --------------------------------------------------------------------------- #
# `--json` — the seam a UI or a spreadsheet reads
#
# Phase 8 is deferred, but the shape of the pipeline is fresh now. The point of
# the flag is that a caller never has to parse rendered prose to find out what
# happened, so the empty case is the one that matters.
# --------------------------------------------------------------------------- #


def test_status_json_is_parseable_and_carries_the_jd_fields(wired) -> None:
    import json

    jd_id = seed(wired)
    runner.invoke(app, ["apply", str(jd_id), "--channel", "linkedin"])

    result = runner.invoke(app, ["status", "--json"])

    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [row["jd_id"] for row in rows] == [jd_id]
    # Flattened, so the caller does not have to join against the JD table.
    assert rows[0]["company"] == "Colonial First State"
    assert rows[0]["status"] == "applied"


def test_an_empty_pipeline_is_an_empty_list_not_a_sentence(wired) -> None:
    """A caller that has to read English to learn there is nothing has no seam
    at all."""
    import json

    result = runner.invoke(app, ["status", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_status_without_json_still_prints_the_table(wired) -> None:
    jd_id = seed(wired)
    runner.invoke(app, ["apply", str(jd_id), "--channel", "linkedin"])

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    # Not the full company name: rich sizes columns to the terminal and wraps
    # it, so asserting the whole string tests the width of the test runner.
    assert "Colonial" in result.stdout
