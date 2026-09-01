"""Unit tests for SQLite persistence. No LLM, no network."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from jobagent.core import store
from jobagent.core.models import (
    Application,
    ApplicationStatus,
    ChallengePoint,
    ConstraintCheck,
    ConstraintStatus,
    FitAssessment,
    HiringStatus,
    MatchStatus,
    RequirementMatch,
    Seniority,
    Verdict,
    Worth,
    JobDescription,
    SalaryRange,
    WorkArrangement,
    WorkType,
)
from jobagent.core.store import StoreError


@pytest.fixture
def conn():
    connection = store.connect(":memory:")
    yield connection
    connection.close()


def make_jd(**overrides) -> JobDescription:
    data = {
        "title": "Engineering Manager",
        "company": "Acme",
        "location": "Sydney CBD",
        "work_type": WorkType.permanent,
        "work_arrangement": WorkArrangement.hybrid,
        "salary_range": SalaryRange(min_aud=160000, max_aud=190000, raw="$160k–$190k"),
        "seniority": Seniority.manager,
        "posted_by": "Acme",
        "hiring_status": HiringStatus.open,
        "must_haves": ["Team leadership", "PHP"],
        "nice_to_haves": ["AWS"],
        "tech_stack": ["PHP", "Vue.js"],
        "responsibilities": ["Lead a team of 8"],
        "red_flags": [],
        "source": "seek",
        "raw_text": "Engineering Manager at Acme. Sydney CBD. Hybrid.",
        "ingested_at": datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return JobDescription(**data)


# --------------------------------------------------------------------------- #
# Round-tripping
# --------------------------------------------------------------------------- #


def test_add_and_get_round_trip(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())
    fetched = store.get_jd(conn, jd_id)

    assert fetched is not None
    assert fetched.id == jd_id
    assert fetched.title == "Engineering Manager"
    assert fetched.work_type is WorkType.permanent
    assert fetched.work_arrangement is WorkArrangement.hybrid
    assert fetched.must_haves == ["Team leadership", "PHP"]
    assert fetched.tech_stack == ["PHP", "Vue.js"]
    assert fetched.salary_range is not None
    assert fetched.salary_range.min_aud == 160000


def test_raw_text_is_preserved_verbatim(conn) -> None:
    # Re-parsing an old JD after a prompt change depends on this.
    raw = "  Ragged   whitespace\n\nand blank lines.\t Kept exactly.  " + "x" * 200
    jd_id = store.add_jd(conn, make_jd(raw_text=raw))

    assert store.get_jd(conn, jd_id).raw_text == raw


def test_empty_lists_round_trip(conn) -> None:
    jd_id = store.add_jd(
        conn,
        make_jd(must_haves=[], nice_to_haves=[], tech_stack=[], responsibilities=[]),
    )
    fetched = store.get_jd(conn, jd_id)

    assert fetched.must_haves == []
    assert fetched.tech_stack == []


def test_absent_salary_round_trips_as_none(conn) -> None:
    jd_id = store.add_jd(conn, make_jd(salary_range=None))

    assert store.get_jd(conn, jd_id).salary_range is None


def test_naive_timestamp_is_stored_as_utc(conn) -> None:
    jd_id = store.add_jd(conn, make_jd(ingested_at=datetime(2026, 8, 31, 3, 0)))

    stored = conn.execute(
        "SELECT ingested_at FROM job_descriptions WHERE id = ?", (jd_id,)
    ).fetchone()[0]
    assert stored.endswith("+00:00")


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #


def test_get_missing_returns_none(conn) -> None:
    assert store.get_jd(conn, 999) is None


def test_list_is_empty_initially(conn) -> None:
    assert store.list_jds(conn) == []


def test_list_returns_newest_first(conn) -> None:
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    for offset, title in enumerate(["oldest", "middle", "newest"]):
        store.add_jd(
            conn, make_jd(title=title, ingested_at=base + timedelta(days=offset))
        )

    assert [jd.title for jd in store.list_jds(conn)] == ["newest", "middle", "oldest"]


def test_list_respects_limit(conn) -> None:
    for index in range(5):
        store.add_jd(conn, make_jd(title=f"role {index}"))

    assert len(store.list_jds(conn, limit=2)) == 2


def test_delete_removes_the_row(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())

    assert store.delete_jd(conn, jd_id) is True
    assert store.get_jd(conn, jd_id) is None
    assert store.delete_jd(conn, jd_id) is False


# --------------------------------------------------------------------------- #
# Schema and corruption
# --------------------------------------------------------------------------- #


def test_schema_version_is_recorded(conn) -> None:
    value = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()

    assert value[0] == str(store.SCHEMA_VERSION)


def test_init_schema_is_idempotent(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())
    store.init_schema(conn)  # simulates a second connect against the same file

    assert store.get_jd(conn, jd_id) is not None


def test_connect_creates_parent_directories(tmp_path) -> None:
    db_path = tmp_path / "nested" / "deeper" / "jobagent.db"

    with store.open_store(db_path) as conn:
        store.add_jd(conn, make_jd())

    assert db_path.exists()


def test_open_store_closes_the_connection(tmp_path) -> None:
    with store.open_store(tmp_path / "jobagent.db") as conn:
        pass

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_corrupt_list_column_raises_store_error(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())
    conn.execute(
        "UPDATE job_descriptions SET tech_stack = ? WHERE id = ?", ("not json", jd_id)
    )

    with pytest.raises(StoreError, match="not valid JSON"):
        store.get_jd(conn, jd_id)


def test_list_column_holding_a_non_list_raises(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())
    conn.execute(
        "UPDATE job_descriptions SET tech_stack = ? WHERE id = ?",
        (json.dumps({"php": True}), jd_id),
    )

    with pytest.raises(StoreError, match="expected a list"):
        store.get_jd(conn, jd_id)


def test_row_that_no_longer_validates_raises(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())
    conn.execute(
        "UPDATE job_descriptions SET work_type = ? WHERE id = ?", ("freelance", jd_id)
    )

    with pytest.raises(StoreError, match="no longer matches the model"):
        store.get_jd(conn, jd_id)


# --------------------------------------------------------------------------- #
# Schema v3
# --------------------------------------------------------------------------- #


def test_agency_and_status_fields_round_trip(conn) -> None:
    jd = make_jd(
        company=None,
        posted_by="Harvey Robinson Pty Ltd",
        via_agency=True,
        hiring_status=HiringStatus.closed,
        multiple_roles=True,
        seniority=Seniority.lead,
    )
    jd_id = store.add_jd(conn, jd)

    loaded = store.get_jd(conn, jd_id)

    assert loaded is not None
    assert loaded.company is None
    assert loaded.posted_by == "Harvey Robinson Pty Ltd"
    assert loaded.via_agency is True
    assert loaded.hiring_status is HiringStatus.closed
    assert loaded.multiple_roles is True
    assert loaded.seniority is Seniority.lead


def test_defaults_round_trip(conn) -> None:
    """An ad that says nothing about any of it."""
    jd_id = store.add_jd(conn, make_jd(posted_by=None, hiring_status=HiringStatus.unknown))

    loaded = store.get_jd(conn, jd_id)

    assert loaded is not None
    assert loaded.via_agency is False
    assert loaded.multiple_roles is False
    assert loaded.hiring_status is HiringStatus.unknown


def test_a_v2_database_gains_the_v3_columns(tmp_path) -> None:
    """The additive-column path is the only migration machinery there is, so
    the columns added for the agency and status findings have to go through
    it — a database written before them must still open and read."""
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE job_descriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, company TEXT, location TEXT,
            work_type TEXT NOT NULL, work_arrangement TEXT NOT NULL,
            salary_json TEXT, seniority TEXT,
            must_haves TEXT NOT NULL DEFAULT '[]',
            nice_to_haves TEXT NOT NULL DEFAULT '[]',
            tech_stack TEXT NOT NULL DEFAULT '[]',
            responsibilities TEXT NOT NULL DEFAULT '[]',
            red_flags TEXT NOT NULL DEFAULT '[]',
            source TEXT, source_url TEXT, source_metadata TEXT,
            raw_text TEXT NOT NULL, ingested_at TEXT NOT NULL
        );
        INSERT INTO job_descriptions
            (title, work_type, work_arrangement, seniority, raw_text, ingested_at)
        VALUES ('Engineering Manager', 'permanent', 'hybrid', 'unknown',
                'Engineering Manager at Acme.', '2026-08-31T03:00:00+00:00');
        """
    )
    old.commit()
    old.close()

    with store.open_store(path) as conn:
        loaded = store.get_jd(conn, 1)
        version = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()[0]

    assert version == str(store.SCHEMA_VERSION)
    assert loaded is not None
    assert loaded.via_agency is False
    assert loaded.hiring_status is HiringStatus.unknown


# --------------------------------------------------------------------------- #
# Fit assessments
# --------------------------------------------------------------------------- #


def make_assessment(jd_id: int, **overrides) -> FitAssessment:
    data = {
        "jd_id": jd_id,
        "overall_score": 72,
        "recruiter_screen_score": 48,
        "verdict": Verdict.apply_with_caveats,
        "rationale": "On target, but the office location is unstated.",
        "target_role_match": True,
        "target_role_note": "Engineering Manager.",
        "constraints": [
            ConstraintCheck(
                name="location",
                status=ConstraintStatus.unknown,
                detail="On-site, no suburb named.",
                question="Which office?",
            )
        ],
        "requirements": [
            RequirementMatch(
                requirement="5+ years managing teams",
                status=MatchStatus.met,
                evidence_ref="acme_em",
                note="Two squads for three years.",
            )
        ],
        "emphasise": ["Lead with the founder track"],
        "challenge_points": [
            ChallengePoint(point="Why leaving?", response="The recorded reason.")
        ],
        "profile_gaps": ["No Kubernetes anywhere"],
        "questions_to_ask": ["Which office?"],
        "model_used": "claude-sonnet-5",
        "scored_at": datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return FitAssessment(**data)


def test_assessment_round_trips_with_its_nested_objects(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())

    store.add_assessment(conn, make_assessment(jd_id))
    loaded = store.latest_assessment(conn, jd_id)

    assert loaded is not None
    assert loaded.verdict is Verdict.apply_with_caveats
    assert loaded.constraints[0].status is ConstraintStatus.unknown
    assert loaded.constraints[0].question == "Which office?"
    assert loaded.requirements[0].status is MatchStatus.met
    assert loaded.requirements[0].evidence_ref == "acme_em"
    assert loaded.challenge_points[0].point == "Why leaving?"
    assert loaded.profile_gaps == ["No Kubernetes anywhere"]


def test_rescoring_keeps_both_runs(conn) -> None:
    """The eval harness compares a prompt change against what came before, so
    an assessment must never overwrite its predecessor."""
    jd_id = store.add_jd(conn, make_jd())
    store.add_assessment(conn, make_assessment(jd_id, overall_score=40))
    store.add_assessment(
        conn,
        make_assessment(
            jd_id,
            overall_score=80,
            scored_at=datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc),
        ),
    )

    history = store.list_assessments(conn, jd_id)

    assert [a.overall_score for a in history] == [80, 40]
    assert store.latest_assessment(conn, jd_id).overall_score == 80


def test_list_assessments_can_narrow_to_one_model(conn) -> None:
    """A cheap comparison run sitting between two real ones turns a prompt
    diff into a provider diff. `eval diff --model` reads through this."""
    jd_id = store.add_jd(conn, make_jd())
    store.add_assessment(conn, make_assessment(jd_id, overall_score=40))
    store.add_assessment(
        conn,
        make_assessment(
            jd_id,
            overall_score=5,
            model_used="gemini-2.5-flash",
            scored_at=datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc),
        ),
    )
    store.add_assessment(
        conn,
        make_assessment(
            jd_id,
            overall_score=44,
            scored_at=datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc),
        ),
    )

    everything = store.list_assessments(conn, jd_id)
    sonnet = store.list_assessments(conn, jd_id, model="claude-sonnet-5")

    # Unfiltered, the two newest span two providers — a 39-point "regression".
    assert [a.overall_score for a in everything] == [44, 5, 40]
    assert [a.overall_score for a in sonnet] == [44, 40]


def test_no_assessment_yet_is_none_not_an_error(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())

    assert store.latest_assessment(conn, jd_id) is None
    assert store.list_assessments(conn, jd_id) == []


def test_deleting_a_jd_takes_its_assessments_with_it(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())
    store.add_assessment(conn, make_assessment(jd_id))

    store.delete_jd(conn, jd_id)

    assert store.list_assessments(conn, jd_id) == []


def test_free_text_seniority_from_an_older_row_is_normalised(tmp_path) -> None:
    """Seniority was free text until the eleven-ad prompt pass. Rows written
    then hold "Engineering Manager", which no longer validates — without this
    the store raises on every read of them."""
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE job_descriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, company TEXT, location TEXT,
            work_type TEXT NOT NULL, work_arrangement TEXT NOT NULL,
            salary_json TEXT, seniority TEXT,
            must_haves TEXT NOT NULL DEFAULT '[]',
            nice_to_haves TEXT NOT NULL DEFAULT '[]',
            tech_stack TEXT NOT NULL DEFAULT '[]',
            responsibilities TEXT NOT NULL DEFAULT '[]',
            red_flags TEXT NOT NULL DEFAULT '[]',
            source TEXT, source_url TEXT, source_metadata TEXT,
            raw_text TEXT NOT NULL, ingested_at TEXT NOT NULL
        );
        INSERT INTO job_descriptions
            (title, work_type, work_arrangement, seniority, raw_text, ingested_at)
        VALUES
            ('EM', 'permanent', 'hybrid', 'Engineering Manager', 'x', '2026-08-31T03:00:00+00:00'),
            ('Lead', 'permanent', 'hybrid', 'Lead', 'x', '2026-08-31T03:00:00+00:00'),
            ('Odd', 'permanent', 'hybrid', 'Chief Wizard', 'x', '2026-08-31T03:00:00+00:00');
        """
    )
    old.commit()
    old.close()

    with store.open_store(path) as conn:
        loaded = {jd.title: jd.seniority for jd in store.list_jds(conn)}

    assert loaded["EM"] is Seniority.manager
    assert loaded["Lead"] is Seniority.lead
    # Not guessed from prose — `unknown` is a first-class value.
    assert loaded["Odd"] is Seniority.unknown


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #


def make_application(jd_id: int, **overrides) -> Application:
    data = {
        "jd_id": jd_id,
        "status": ApplicationStatus.applied,
        "applied_on": date(2026, 8, 7),
        "channel": "seek",
        "notes": "Applied through the portal.",
        "updated_at": datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return Application(**data)


def test_an_application_round_trips(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())

    store.save_application(conn, make_application(jd_id))
    loaded = store.get_application(conn, jd_id)

    assert loaded is not None
    assert loaded.status is ApplicationStatus.applied
    assert loaded.applied_on == date(2026, 8, 7)
    assert loaded.channel == "seek"


def test_recording_an_outcome_replaces_rather_than_appends(conn) -> None:
    """Unlike an assessment, an application has one current truth. The history
    that matters — what the scorer said, and when — is in fit_assessments."""
    jd_id = store.add_jd(conn, make_jd())
    store.save_application(conn, make_application(jd_id))

    store.save_application(
        conn,
        make_application(
            jd_id,
            status=ApplicationStatus.interview_2,
            worth_applying=Worth.yes,
            worth_why="Two interviews.",
        ),
    )

    assert len(store.list_applications(conn)) == 1
    loaded = store.get_application(conn, jd_id)
    assert loaded.status is ApplicationStatus.interview_2
    assert loaded.worth_applying is Worth.yes


def test_the_derived_marker_survives_a_round_trip(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())

    store.save_application(conn, make_application(jd_id, worth_derived=True))

    assert store.get_application(conn, jd_id).worth_derived is True


def test_no_application_yet_is_none_not_an_error(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())

    assert store.get_application(conn, jd_id) is None


def test_deleting_a_jd_takes_its_application_with_it(conn) -> None:
    jd_id = store.add_jd(conn, make_jd())
    store.save_application(conn, make_application(jd_id))

    store.delete_jd(conn, jd_id)

    assert store.list_applications(conn) == []
