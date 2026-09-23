"""`jobagent jd delete` — removing a duplicate that should never have existed.

Written after a recruiter-sourced role forked across JD 46 and JD 47: the same
chat thread ingested twice, 46 holding the application and 47 holding the better
text. `jd amend` fixed the fork, which left 47 as dead weight with no way to
remove it.

Two hazards shape the guards. Foreign keys cascade, so deleting an ad takes its
assessments — and an application row, which is the pipeline record and what
`eval` is built from. And two ads can resolve to the *same* output folder (46
and 47 both landed in the same one), so deleting documents
alongside the row could destroy another application's work.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from jobagent.adapters import docs
from jobagent.cli import jd as jd_cli
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
NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def flat(output: str) -> str:
    return " ".join(output.split())


@pytest.fixture
def wired(tmp_path, monkeypatch):
    config = Config(
        _env_file=None,
        db_path=tmp_path / "jobagent.db",
        jd_dir=tmp_path,
        output_dir=tmp_path / "out",
    )
    monkeypatch.setattr(jd_cli, "get_config", lambda: config)
    return config


def seed_jd(
    config, *, title: str = "AI Engineer", company: str | None = "Northwind"
) -> int:
    with store.open_store(config.db_path) as conn:
        return store.add_jd(
            conn,
            JobDescription(
                title=title,
                company=company,
                work_type=WorkType.permanent,
                work_arrangement=WorkArrangement.hybrid,
                raw_text="Drive an agentic delivery lifecycle rollout. " * 20,
                ingested_at=NOW,
            ),
        )


def seed_assessment(config, jd_id: int, *, score: int = 34) -> int:
    with store.open_store(config.db_path) as conn:
        return store.add_assessment(
            conn,
            FitAssessment(
                jd_id=jd_id,
                overall_score=score,
                recruiter_screen_score=38,
                verdict=Verdict.skip,
                rationale="Named must-haves are absent from the profile.",
                target_role_match=True,
                target_role_note="Engineering Manager.",
                scored_at=NOW,
            ),
        )


def seed_application(config, jd_id: int) -> int:
    with store.open_store(config.db_path) as conn:
        return store.save_application(
            conn,
            Application(
                jd_id=jd_id,
                status=ApplicationStatus.recruiter_call,
                channel="recruiter — agency",
                notes="Prescreen done.\nSecond stage pending.",
                worth_applying=Worth.yes,
                updated_at=NOW,
            ),
        )


def test_deletes_a_duplicate_and_says_so(wired):
    jd_id = seed_jd(wired)

    result = runner.invoke(app, ["jd", "delete", str(jd_id), "--yes"])

    assert result.exit_code == 0, result.output
    assert "Deleted" in result.output
    with store.open_store(wired.db_path) as conn:
        assert store.get_jd(conn, jd_id) is None


def test_reports_the_assessments_it_will_cascade(wired):
    jd_id = seed_jd(wired)
    seed_assessment(wired, jd_id)

    result = runner.invoke(app, ["jd", "delete", str(jd_id), "--yes"])

    assert result.exit_code == 0, result.output
    # The count is named before anything is removed, not discovered after.
    assert "1 assessment" in flat(result.output)
    assert "eval" in result.output
    with store.open_store(wired.db_path) as conn:
        assert store.list_assessments(conn, jd_id) == []


def test_refuses_when_an_application_is_recorded(wired):
    jd_id = seed_jd(wired)
    seed_application(wired, jd_id)

    result = runner.invoke(app, ["jd", "delete", str(jd_id), "--yes"])

    assert result.exit_code == 2, result.output
    assert "application is recorded" in flat(result.output)
    # Nothing was touched: refusing has to actually refuse.
    with store.open_store(wired.db_path) as conn:
        assert store.get_jd(conn, jd_id) is not None
        assert store.get_application(conn, jd_id) is not None


def test_force_deletes_despite_the_application(wired):
    jd_id = seed_jd(wired)
    seed_application(wired, jd_id)

    result = runner.invoke(app, ["jd", "delete", str(jd_id), "--yes", "--force"])

    assert result.exit_code == 0, result.output
    with store.open_store(wired.db_path) as conn:
        assert store.get_jd(conn, jd_id) is None
        assert store.get_application(conn, jd_id) is None


def test_declining_the_prompt_leaves_it_alone(wired):
    jd_id = seed_jd(wired)

    result = runner.invoke(app, ["jd", "delete", str(jd_id)], input="n\n")

    assert result.exit_code == 1, result.output
    with store.open_store(wired.db_path) as conn:
        assert store.get_jd(conn, jd_id) is not None


def test_confirming_the_prompt_deletes(wired):
    jd_id = seed_jd(wired)

    result = runner.invoke(app, ["jd", "delete", str(jd_id)], input="y\n")

    assert result.exit_code == 0, result.output
    with store.open_store(wired.db_path) as conn:
        assert store.get_jd(conn, jd_id) is None


def test_unknown_id_is_an_error(wired):
    result = runner.invoke(app, ["jd", "delete", "999", "--yes"])

    assert result.exit_code == 1, result.output
    assert "No job description with id 999" in flat(result.output)


def test_documents_on_disk_are_reported_and_never_removed(wired):
    """The 46/47 hazard: two ads sharing one folder.

    Deleting the row must not reach the documents, because the folder may hold
    another application's resume — the one that was actually sent.
    """
    jd_id = seed_jd(wired)
    other_id = seed_jd(wired)
    with store.open_store(wired.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
    folder = docs.application_folder(wired.output_dir, jd)
    sent = folder / "AlanBron_Resume_Northwind_202609.docx"
    sent.write_text("the resume that was actually sent")

    result = runner.invoke(app, ["jd", "delete", str(jd_id), "--yes"])

    assert result.exit_code == 0, result.output
    assert "untouched" in result.output
    assert sent.exists()
    assert sent.read_text() == "the resume that was actually sent"
    # The duplicate that shares the folder is untouched too.
    with store.open_store(wired.db_path) as conn:
        assert store.get_jd(conn, other_id) is not None
