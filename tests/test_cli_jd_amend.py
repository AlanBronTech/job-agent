"""`jobagent jd amend` — re-parsing a stored ad in place when more of it arrives.

An ad is not immutable, and the tool used to assume it was. A recruiter answered
a question in chat and the real job description turned up after the teaser, both
inside three days, and each one forked the role across two records: the second
holding the better text, the first holding the application, its channel and
every note. `spend --jd` then split the cost of one role across two ids.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from jobagent.cli import jd as jd_cli
from jobagent.cli import score as score_cli
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
NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)

TEASER = "We are hiring an AI Engineer. Drive our agentic rollout. " * 20
REAL_JD = "Senior Manager, AI Product Delivery Engineering. " * 20


def flat(output: str) -> str:
    return " ".join(output.split())


@pytest.fixture
def wired(tmp_path, monkeypatch):
    config = Config(_env_file=None, db_path=tmp_path / "jobagent.db", jd_dir=tmp_path)
    monkeypatch.setattr(jd_cli, "get_config", lambda: config)
    monkeypatch.setattr(score_cli, "get_config", lambda: config)
    return config


def seed(config, raw_text: str = TEASER) -> int:
    with store.open_store(config.db_path) as conn:
        return store.add_jd(
            conn,
            JobDescription(
                title="AI Engineer",
                company="Colonial First State",
                work_type=WorkType.permanent,
                work_arrangement=WorkArrangement.hybrid,
                raw_text=raw_text,
                ingested_at=NOW,
            ),
        )


def stub_parse(monkeypatch, **fields):
    """Replace the model call. What the parser returns is `test_jd`'s problem."""
    seen: dict[str, str] = {}

    def fake(raw_text, *, client, source=None):
        seen["raw_text"] = raw_text
        data = {
            "title": "Senior Manager, AI Product Delivery Engineering",
            "company": "Colonial First State",
            "work_type": WorkType.permanent,
            "work_arrangement": WorkArrangement.hybrid,
            "raw_text": raw_text,
            "ingested_at": NOW,
        }
        data.update(fields)
        return JobDescription(**data)

    monkeypatch.setattr(jd_cli, "parse_jd", fake)
    monkeypatch.setattr(jd_cli, "get_client", lambda *a, **k: object())
    return seen


def write_jd_file(config, name: str, text: str):
    path = config.jd_dir / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# The id survives — which is the entire point
# --------------------------------------------------------------------------- #


def test_amending_keeps_the_id_and_everything_hanging_off_it(
    wired, monkeypatch
) -> None:
    jd_id = seed(wired)
    with store.open_store(wired.db_path) as conn:
        store.save_application(
            conn,
            Application(
                jd_id=jd_id,
                status=ApplicationStatus.recruiter_call,
                channel="recruiter — Upgrowth",
                notes="Phoned about a 2pm interview.",
                worth_applying=Worth.unsure,
                updated_at=NOW,
            ),
        )
    stub_parse(monkeypatch)
    write_jd_file(wired, "real.txt", REAL_JD)

    result = runner.invoke(app, ["jd", "amend", str(jd_id), "--file", "real.txt"])

    assert result.exit_code == 0
    with store.open_store(wired.db_path) as conn:
        assert len(store.list_jds(conn)) == 1  # not forked into a second record
        application = store.get_application(conn, jd_id)
    assert application.channel == "recruiter — Upgrowth"
    assert "2pm interview" in application.notes


def test_the_new_text_replaces_the_old(wired, monkeypatch) -> None:
    jd_id = seed(wired)
    seen = stub_parse(monkeypatch)
    write_jd_file(wired, "real.txt", REAL_JD)

    runner.invoke(app, ["jd", "amend", str(jd_id), "--file", "real.txt"])

    assert TEASER not in seen["raw_text"]
    with store.open_store(wired.db_path) as conn:
        assert store.get_jd(conn, jd_id).title.startswith("Senior Manager")


def test_append_parses_the_old_text_with_the_new(wired, monkeypatch) -> None:
    """A chat thread that grew. Replacing there would throw away the half of
    the conversation that named the company."""
    jd_id = seed(wired)
    seen = stub_parse(monkeypatch)
    write_jd_file(wired, "more.txt", "And the band is $185,000.")

    result = runner.invoke(
        app, ["jd", "amend", str(jd_id), "--file", "more.txt", "--append"]
    )

    assert result.exit_code == 0
    assert TEASER.strip() in seen["raw_text"]
    assert "185,000" in seen["raw_text"]


def test_the_superseded_text_is_kept(wired, monkeypatch) -> None:
    """Amending is not deleting. The ad as it first arrived is evidence."""
    jd_id = seed(wired)
    stub_parse(monkeypatch)
    write_jd_file(wired, "real.txt", REAL_JD)

    runner.invoke(app, ["jd", "amend", str(jd_id), "--file", "real.txt"])

    with store.open_store(wired.db_path) as conn:
        row = conn.execute(
            "SELECT superseded_text, amended_at FROM job_descriptions WHERE id = ?",
            (jd_id,),
        ).fetchone()
    assert TEASER.strip() in row[0]
    assert row[1] is not None


def test_ingested_at_is_not_touched(wired, monkeypatch) -> None:
    """When the ad first arrived is a fact about the pipeline. It does not
    change because more of it turned up later — the Ebury repost case turns on
    exactly this kind of date."""
    jd_id = seed(wired)
    stub_parse(monkeypatch)
    write_jd_file(wired, "real.txt", REAL_JD)

    runner.invoke(app, ["jd", "amend", str(jd_id), "--file", "real.txt"])

    with store.open_store(wired.db_path) as conn:
        assert store.get_jd(conn, jd_id).ingested_at == NOW


def test_what_changed_is_named(wired, monkeypatch) -> None:
    """The point of an amendment is usually one or two facts. Reprinting the
    whole ad buries them."""
    jd_id = seed(wired)
    stub_parse(monkeypatch, work_arrangement=WorkArrangement.onsite)
    write_jd_file(wired, "real.txt", REAL_JD)

    result = runner.invoke(app, ["jd", "amend", str(jd_id), "--file", "real.txt"])

    output = flat(result.stdout)
    assert "Changed" in output
    assert "arrangement" in output and "onsite" in output


def test_amending_an_unknown_id_is_refused(wired, monkeypatch) -> None:
    stub_parse(monkeypatch)
    write_jd_file(wired, "real.txt", REAL_JD)

    result = runner.invoke(app, ["jd", "amend", "999", "--file", "real.txt"])

    assert result.exit_code == 1
    assert "No job description with id 999" in flat(result.stderr)


# --------------------------------------------------------------------------- #
# A stored assessment now describes a different ad
# --------------------------------------------------------------------------- #


def score_it(config, jd_id: int, when: datetime) -> None:
    with store.open_store(config.db_path) as conn:
        store.add_assessment(
            conn,
            FitAssessment(
                jd_id=jd_id,
                overall_score=57,
                recruiter_screen_score=48,
                verdict=Verdict.apply_with_caveats,
                rationale="Scored against the teaser.",
                target_role_match=True,
                target_role_note="Closest fit is AI Enablement Lead.",
                scored_at=when,
            ),
        )


def test_an_assessment_from_before_the_amendment_is_reported(
    wired, monkeypatch
) -> None:
    jd_id = seed(wired)
    score_it(wired, jd_id, NOW - timedelta(days=2))
    stub_parse(monkeypatch)
    write_jd_file(wired, "real.txt", REAL_JD)

    result = runner.invoke(app, ["jd", "amend", str(jd_id), "--file", "real.txt"])

    assert "predate this amendment" in flat(result.stderr)


def test_score_last_says_the_assessment_is_of_a_different_ad(
    wired, monkeypatch
) -> None:
    """`--last` is free, so it is the read most likely to be trusted without
    thinking about when it was produced."""
    jd_id = seed(wired)
    score_it(wired, jd_id, NOW - timedelta(days=2))
    stub_parse(monkeypatch)
    write_jd_file(wired, "real.txt", REAL_JD)
    runner.invoke(app, ["jd", "amend", str(jd_id), "--file", "real.txt"])

    result = runner.invoke(app, ["score", str(jd_id), "--last"])

    assert result.exit_code == 0
    assert "predates an amendment" in flat(result.stderr)


def test_an_assessment_made_after_the_amendment_is_not_flagged(
    wired, monkeypatch
) -> None:
    """A guard that fires when nothing is at risk stops being a guard."""
    jd_id = seed(wired)
    stub_parse(monkeypatch)
    write_jd_file(wired, "real.txt", REAL_JD)
    runner.invoke(app, ["jd", "amend", str(jd_id), "--file", "real.txt"])
    score_it(wired, jd_id, datetime.now(timezone.utc) + timedelta(minutes=1))

    result = runner.invoke(app, ["score", str(jd_id), "--last"])

    assert "predates an amendment" not in flat(result.stderr)


def test_an_unamended_jd_never_warns(wired) -> None:
    jd_id = seed(wired)
    score_it(wired, jd_id, NOW)

    result = runner.invoke(app, ["score", str(jd_id), "--last"])

    assert "predates an amendment" not in flat(result.stderr)


def test_a_rescore_after_an_amendment_is_not_flagged_stale(wired, monkeypatch) -> None:
    """The sequence that actually happens, and that the first version of this
    guard got wrong within a minute of shipping.

    Score, amend, re-score, read. The old assessment is still in the history —
    nothing deletes it — so a check that counts stale assessments finds one and
    warns about a result produced seconds ago. `--last` shows exactly one
    assessment and the question is whether *that* one is stale.
    """
    jd_id = seed(wired)
    score_it(wired, jd_id, NOW - timedelta(days=8))  # scored against the teaser
    stub_parse(monkeypatch)
    write_jd_file(wired, "real.txt", REAL_JD)
    runner.invoke(app, ["jd", "amend", str(jd_id), "--file", "real.txt"])
    score_it(wired, jd_id, datetime.now(timezone.utc) + timedelta(seconds=30))

    result = runner.invoke(app, ["score", str(jd_id), "--last"])

    assert result.exit_code == 0
    assert "predates an amendment" not in flat(result.stderr)


def test_the_amendment_still_counts_the_whole_stale_history(wired, monkeypatch) -> None:
    """`jd amend` asks a different question from `score --last` and should keep
    asking it: how much of this history describes an older ad."""
    jd_id = seed(wired)
    score_it(wired, jd_id, NOW - timedelta(days=8))
    score_it(wired, jd_id, NOW - timedelta(days=2))
    stub_parse(monkeypatch)
    write_jd_file(wired, "real.txt", REAL_JD)

    result = runner.invoke(app, ["jd", "amend", str(jd_id), "--file", "real.txt"])

    assert "2 stored assessment(s) predate this amendment" in flat(result.stderr)
