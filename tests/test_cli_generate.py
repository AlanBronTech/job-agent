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


# --------------------------------------------------------------------------- #
# Not overwriting documents already generated
# --------------------------------------------------------------------------- #


def seed_worth_generating(config) -> int:
    """An ad the scorer is happy with, so the skip guard does not do the work."""
    with store.open_store(config.db_path) as conn:
        jd_id = store.add_jd(conn, make_jd("Senior Manager, AI Product Delivery"))
        store.add_assessment(
            conn,
            FitAssessment(
                jd_id=jd_id,
                overall_score=57,
                recruiter_screen_score=48,
                verdict=Verdict.apply_with_caveats,
                rationale="Worth the day if location and band clear.",
                target_role_match=True,
                target_role_note="Close to AI enablement lead.",
                scored_at=NOW,
            ),
        )
        return jd_id


def already_generated(config, jd_id: int) -> "tuple":
    """Put a resume and the two records where an earlier run would have left
    them, and hand back the folder and the resume's prior contents."""
    from datetime import date

    from jobagent.adapters import docs
    from jobagent.core import store as _store

    with _store.open_store(config.db_path) as conn:
        jd = _store.get_jd(conn, jd_id)
    today = date.today()
    folder = docs.application_folder(config.output_dir, jd, when=today)
    resume = folder / docs.document_name("Resume", jd, when=today)
    resume.write_text("the resume that was sent", encoding="utf-8")
    docs.write_text(folder, "assessment.md", "the earlier assessment")
    return folder, resume


def test_it_refuses_to_overwrite_documents_from_an_earlier_run(wired) -> None:
    """The failure this guards against cost a real set of documents: `generate`
    rewrote a folder from three days earlier, in place, with no warning."""
    jd_id = seed_worth_generating(wired)
    _, resume = already_generated(wired, jd_id)

    result = runner.invoke(app, ["generate", str(jd_id), "--resume"])

    output = " ".join(result.output.split())
    assert result.exit_code == 2
    assert "Already generated" in output
    assert "--overwrite" in output
    assert resume.name in output
    # The point of the guard: the earlier work is still on disk.
    assert resume.read_text(encoding="utf-8") == "the resume that was sent"


def test_the_refusal_names_only_what_this_run_would_write(wired) -> None:
    """Without --cover, the cover letter is not at risk and is not listed."""
    jd_id = seed_worth_generating(wired)
    folder, _ = already_generated(wired, jd_id)
    (folder / "interview-prep.md").write_text("from a prep run", encoding="utf-8")

    result = runner.invoke(app, ["generate", str(jd_id), "--resume"])

    output = " ".join(result.output.split())
    assert "assessment.md" in output
    assert "interview-prep.md" not in output
    assert "CoverLetter" not in output


def test_overwrite_gets_past_the_guard(wired) -> None:
    """It stops at the next gate — a missing profile — not at the folder.

    Proves the flag is what releases it without paying for a model call.
    """
    jd_id = seed_worth_generating(wired)
    already_generated(wired, jd_id)

    result = runner.invoke(app, ["generate", str(jd_id), "--resume", "--overwrite"])

    assert "Already generated" not in result.output
    assert "No profile directory" in result.output


def test_a_first_run_is_not_blocked(wired) -> None:
    jd_id = seed_worth_generating(wired)

    result = runner.invoke(app, ["generate", str(jd_id), "--resume"])

    assert "Already generated" not in result.output
    assert "No profile directory" in result.output


# --------------------------------------------------------------------------- #
# --supersede: keep the earlier documents under a dated name
# --------------------------------------------------------------------------- #


def test_the_refusal_offers_supersede(wired) -> None:
    jd_id = seed_worth_generating(wired)
    already_generated(wired, jd_id)
    result = runner.invoke(app, ["generate", str(jd_id), "--resume"])
    assert "--supersede" in " ".join(result.output.split())


def test_supersede_gets_past_the_guard_without_moving_a_refused_run(wired) -> None:
    """Past the overwrite guard to the next gate, a missing profile. The run is
    refused there, so the folder must not have been renamed for nothing."""
    jd_id = seed_worth_generating(wired)
    folder, resume = already_generated(wired, jd_id)

    result = runner.invoke(app, ["generate", str(jd_id), "--resume", "--supersede"])

    assert "Already generated" not in result.output
    assert "No profile directory" in result.output
    assert folder.exists() and resume.read_text(encoding="utf-8") == "the resume that was sent"


def _ready_to_spend(wired, monkeypatch, calls):
    """A profile and a client, with the first model call recorded and stopped."""
    from pathlib import Path

    from jobagent.services import documents

    wired.profile_dir = Path(__file__).resolve().parents[1] / "profile.example"
    monkeypatch.setattr(documents, "get_client", lambda *a, **k: object())
    monkeypatch.setattr(documents.role_kind, "ensure", lambda *a, **k: None)

    def first_call(*args, **kwargs):
        calls.append("model")
        raise RuntimeError("stop here")

    monkeypatch.setattr(documents, "build_resume", first_call)


def test_supersede_moves_the_folder_just_before_spending(wired, monkeypatch) -> None:
    jd_id = seed_worth_generating(wired)
    folder, resume = already_generated(wired, jd_id)
    calls = []
    _ready_to_spend(wired, monkeypatch, calls)

    runner.invoke(app, ["generate", str(jd_id), "--resume", "--supersede"])

    assert calls == ["model"]
    assert not folder.exists()
    moved = [p for p in folder.parent.iterdir() if ".superseded-" in p.name]
    assert len(moved) == 1
    assert (moved[0] / resume.name).read_text(encoding="utf-8") == "the resume that was sent"


def test_supersede_with_nothing_to_move_is_a_first_run(wired) -> None:
    jd_id = seed_worth_generating(wired)
    result = runner.invoke(app, ["generate", str(jd_id), "--resume", "--supersede"])
    assert "No profile directory" in result.output


def test_supersede_and_overwrite_together_is_refused(wired) -> None:
    jd_id = seed_worth_generating(wired)
    folder, _ = already_generated(wired, jd_id)
    result = runner.invoke(
        app, ["generate", str(jd_id), "--resume", "--supersede", "--overwrite"]
    )
    assert result.exit_code == 2
    assert "contradict" in result.output
    assert folder.exists()


def test_a_failed_move_spends_nothing_and_leaves_the_folder(wired, monkeypatch) -> None:
    from jobagent.adapters import docs

    jd_id = seed_worth_generating(wired)
    folder, resume = already_generated(wired, jd_id)
    calls = []
    _ready_to_spend(wired, monkeypatch, calls)

    def refuse(*args, **kwargs):
        raise docs.DocsError("permission denied")

    monkeypatch.setattr(docs, "supersede_folder", refuse)
    result = runner.invoke(app, ["generate", str(jd_id), "--resume", "--supersede"])

    output = " ".join(result.output.split())
    assert result.exit_code == 1
    assert "Nothing was spent" in output
    assert calls == []
    assert resume.read_text(encoding="utf-8") == "the resume that was sent"
