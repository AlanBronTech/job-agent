"""SQLite persistence for the pipeline.

Plain SQL against stdlib ``sqlite3`` — no ORM, per CLAUDE.md. Callers pass a
connection in, so a web handler, a test and the CLI all use the same functions
with different lifetimes. Nothing here prints or exits; failures raise
``StoreError``.

Schema notes:

* List fields (must_haves, tech_stack, …) are stored as JSON text rather than
  child tables. They are read and written whole, never queried element-wise, so
  a join table would be cost without benefit. If scoring later needs "every JD
  requiring Angular", revisit — that is the query that would justify it.
* ``raw_text`` is stored in full. Re-parsing an old JD after a prompt change is
  a first-class operation for the eval harness, and it is impossible without
  the original text.
* ``schema_version`` is recorded so a later migration can tell what it is
  looking at. There is no migration machinery yet, deliberately.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from jobagent.core.models import (
    AlertListing,
    Application,
    Contact,
    FitAssessment,
    JobDescription,
    OutsideApplication,
    ReapplyDecision,
    RoleClassification,
    RevisionNote,
    SentDocument,
)

SCHEMA_VERSION = 18

# Columns added after v1. CREATE TABLE IF NOT EXISTS will not add a column to a
# table that already exists, so additive changes are applied explicitly. This is
# not a migration framework and is not pretending to be one: it handles the only
# kind of change that is safe to make without one.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    # v18 — the saved ad an alert listing led to.
    "alert_listings": [("saved_file", "TEXT NOT NULL DEFAULT ''")],
    # v15 — the contract offer a contract ad was matched to (task 7).
    "fit_assessments": [("contract_offer", "TEXT")],
    "applications": [
        ("worth_derived", "INTEGER NOT NULL DEFAULT 0"),
        ("overrode_scorer", "INTEGER NOT NULL DEFAULT 0"),
        # v8
        ("reposted_on", "TEXT"),
    ],
    "job_descriptions": [
        ("source_url", "TEXT"),
        ("source_metadata", "TEXT"),
        # v3
        ("posted_by", "TEXT"),
        ("via_agency", "INTEGER NOT NULL DEFAULT 0"),
        ("hiring_status", "TEXT NOT NULL DEFAULT 'unknown'"),
        ("multiple_roles", "INTEGER NOT NULL DEFAULT 0"),
        # v9 — `jd amend`. An ad is not immutable: a recruiter sends more
        # detail, or the real job description arrives after the teaser. Both
        # happened inside three days.
        ("amended_at", "TEXT"),
        ("superseded_text", "TEXT"),
        # v10 — spec 002. The employer's requisition number, extracted from the
        # text in code; and the saved file the ad was read from.
        ("requisition_id", "TEXT"),
        ("source_file", "TEXT"),
        # v11 — spec 003. The ad's role kind, classified on first need by a
        # separate call. NULL until then; an amendment clears it.
        ("role_kind", "TEXT"),
        ("role_kind_secondary", "TEXT"),
        ("role_kind_reason", "TEXT"),
        # v12 — the cheap first-pass screen: "score" or "skip", why, when,
        # and on which model. Advisory; an amendment clears it.
        ("screen_decision", "TEXT"),
        ("screen_reason", "TEXT"),
        ("screened_at", "TEXT"),
        ("screen_model", "TEXT"),
    ],
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_descriptions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT NOT NULL,
    company          TEXT,
    location         TEXT,
    work_type        TEXT NOT NULL,
    work_arrangement TEXT NOT NULL,
    salary_json      TEXT,
    seniority        TEXT NOT NULL DEFAULT 'unknown',
    posted_by        TEXT,
    via_agency       INTEGER NOT NULL DEFAULT 0,
    hiring_status    TEXT NOT NULL DEFAULT 'unknown',
    multiple_roles   INTEGER NOT NULL DEFAULT 0,
    must_haves       TEXT NOT NULL DEFAULT '[]',
    nice_to_haves    TEXT NOT NULL DEFAULT '[]',
    tech_stack       TEXT NOT NULL DEFAULT '[]',
    responsibilities TEXT NOT NULL DEFAULT '[]',
    red_flags        TEXT NOT NULL DEFAULT '[]',
    source           TEXT,
    source_url       TEXT,
    source_metadata  TEXT,
    raw_text         TEXT NOT NULL,
    ingested_at      TEXT NOT NULL,
    amended_at       TEXT,
    superseded_text  TEXT,
    requisition_id   TEXT,
    source_file      TEXT,
    role_kind        TEXT,
    role_kind_secondary TEXT,
    role_kind_reason TEXT,
    screen_decision  TEXT,
    screen_reason    TEXT,
    screened_at      TEXT,
    screen_model     TEXT
);

CREATE INDEX IF NOT EXISTS idx_jd_company ON job_descriptions (company);
CREATE INDEX IF NOT EXISTS idx_jd_ingested ON job_descriptions (ingested_at);

-- v10. Applications made with no ad in the store: before the tool existed, or
-- straight through a portal. Kept out of `applications`, which every reader,
-- the eval builder first, assumes has an ad behind it.
CREATE TABLE IF NOT EXISTS outside_applications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    company        TEXT NOT NULL,
    title          TEXT NOT NULL,
    requisition_id TEXT,
    applied_on     TEXT NOT NULL,
    channel        TEXT,
    status         TEXT NOT NULL,
    notes          TEXT NOT NULL DEFAULT '',
    linked_jd_id   INTEGER REFERENCES job_descriptions (id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL
);

-- v10. One decision per ad about the reapplication rule: an answer to
-- "possibly the same job" (same / different) or an overrule.
CREATE TABLE IF NOT EXISTS reapply_decisions (
    jd_id      INTEGER PRIMARY KEY REFERENCES job_descriptions (id) ON DELETE CASCADE,
    decision   TEXT NOT NULL CHECK (decision IN ('same', 'different', 'overrule')),
    matched    TEXT NOT NULL,
    decided_at TEXT NOT NULL
);

-- v13. What was actually sent, kept beside what was generated so the two can
-- be compared. Rows are only ever added: a sent copy is the record.
CREATE TABLE IF NOT EXISTS sent_documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    jd_id        INTEGER NOT NULL REFERENCES job_descriptions (id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('resume', 'cover_letter')),
    folder       TEXT NOT NULL,
    name         TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    generated    TEXT,
    as_generated INTEGER NOT NULL DEFAULT 0,
    sent_on      TEXT NOT NULL,
    recorded_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sent_jd ON sent_documents (jd_id);

-- v14. What Alan knows about an application that the ad does not say, given
-- to the writer on every generate. Kept apart from job_descriptions so it
-- never reaches the scorer or the eval: it was not part of the ad.
CREATE TABLE IF NOT EXISTS ad_context (
    jd_id      INTEGER PRIMARY KEY REFERENCES job_descriptions (id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- v14. What Alan asked `revise` to change, in his words. Only ever added to.
CREATE TABLE IF NOT EXISTS revision_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    jd_id      INTEGER NOT NULL REFERENCES job_descriptions (id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('resume', 'cover_letter')),
    note       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    result     TEXT
);

-- v16. People worth staying in touch with, recruiters first (task 5). A
-- contact outlives any one ad, so jd_id is optional and survives its deletion.
CREATE TABLE IF NOT EXISTS contacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    firm          TEXT NOT NULL DEFAULT '',
    kind          TEXT NOT NULL,
    specialty     TEXT NOT NULL DEFAULT '',
    channel       TEXT NOT NULL DEFAULT '',
    first_contact TEXT NOT NULL,
    last_touch    TEXT NOT NULL,
    next_followup TEXT,
    notes         TEXT NOT NULL DEFAULT '',
    jd_id         INTEGER REFERENCES job_descriptions (id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL
);

-- v17. Jobs seen in SEEK and LinkedIn alert emails, one row per job id, with
-- what the filter made of it and what Alan decided after a look. Only what the
-- email said: the job pages are never fetched.
CREATE TABLE IF NOT EXISTS alert_listings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    job_id      TEXT NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    pay         TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    times_seen  INTEGER NOT NULL DEFAULT 1,
    verdict     TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    decision    TEXT,
    decided_at  TEXT,
    note        TEXT NOT NULL DEFAULT '',
    jd_id       INTEGER REFERENCES job_descriptions (id) ON DELETE SET NULL,
    UNIQUE (source, job_id)
);

-- v18. Files in JD_DIR already looked at for a job address, by modification
-- time, so a folder of PDFs is not re-read on every page load.
CREATE TABLE IF NOT EXISTS scanned_files (
    name     TEXT PRIMARY KEY,
    mtime_ns INTEGER NOT NULL,
    source   TEXT,
    job_id   TEXT
);

-- v17. Alert emails already read, so a re-run over the same days does not
-- count a job as seen twice.
CREATE TABLE IF NOT EXISTS alert_emails (
    message_id TEXT PRIMARY KEY,
    read_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fit_assessments (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    jd_id                  INTEGER NOT NULL REFERENCES job_descriptions (id)
                               ON DELETE CASCADE,
    overall_score          INTEGER NOT NULL,
    recruiter_screen_score INTEGER NOT NULL,
    verdict                TEXT NOT NULL,
    rationale              TEXT NOT NULL,
    target_role_match      INTEGER NOT NULL,
    target_role_note       TEXT NOT NULL,
    constraints            TEXT NOT NULL DEFAULT '[]',
    requirements           TEXT NOT NULL DEFAULT '[]',
    emphasise              TEXT NOT NULL DEFAULT '[]',
    challenge_points       TEXT NOT NULL DEFAULT '[]',
    profile_gaps           TEXT NOT NULL DEFAULT '[]',
    questions_to_ask       TEXT NOT NULL DEFAULT '[]',
    model_used             TEXT,
    scored_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fit_jd ON fit_assessments (jd_id);

CREATE TABLE IF NOT EXISTS applications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    jd_id          INTEGER NOT NULL UNIQUE REFERENCES job_descriptions (id)
                       ON DELETE CASCADE,
    status         TEXT NOT NULL,
    applied_on     TEXT,
    channel        TEXT,
    reposted_on    TEXT,
    notes          TEXT NOT NULL DEFAULT '',
    worth_applying TEXT NOT NULL DEFAULT 'unsure',
    worth_why      TEXT NOT NULL DEFAULT '',
    worth_derived  INTEGER NOT NULL DEFAULT 0,
    overrode_scorer INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL
);
"""

_LIST_COLUMNS = (
    "must_haves",
    "nice_to_haves",
    "tech_stack",
    "responsibilities",
    "red_flags",
)

# Same treatment for the assessment: read and written whole, never queried
# element-wise.
_FIT_LIST_COLUMNS = (
    "constraints",
    "requirements",
    "emphasise",
    "challenge_points",
    "profile_gaps",
    "questions_to_ask",
)


class StoreError(Exception):
    """Any persistence failure, including rows that no longer validate."""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open (creating if needed) the database and ensure the schema exists.

    ``:memory:`` is passed through untouched so tests can use it directly.
    """
    if str(db_path) != ":memory:":
        path = Path(db_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        db_path = str(path)

    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as exc:
        raise StoreError(f"Could not open database at {db_path}: {exc}") from exc

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


@contextmanager
def open_store(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """``connect`` as a context manager, closing on the way out."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if absent and stamp the schema version."""
    try:
        conn.executescript(_SCHEMA)
        _apply_added_columns(conn)
        _normalise_seniority(conn)
        # v18: the `saved` decision was renamed `interested`.
        conn.execute("UPDATE alert_listings SET decision = 'interested' WHERE decision = 'saved'")
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not initialise schema: {exc}") from exc


# Free-text seniority values seen in rows written before the field became an
# enum. Anything not listed becomes `unknown`, which is a first-class value —
# guessing a band from prose the model wrote is how a migration invents data.
_SENIORITY_FROM_TEXT = {
    "engineering manager": "manager",
    "manager": "manager",
    "lead": "lead",
    "senior": "senior",
    "director": "director",
    "head of engineering": "director",
    "junior": "junior",
    "mid": "mid",
}

_SENIORITY_VALUES = {
    "junior", "mid", "senior", "lead", "manager", "director", "unknown",
}


def _normalise_seniority(conn: sqlite3.Connection) -> None:
    """Bring pre-v4 rows into the seniority vocabulary.

    Adding a column is safe; changing what an existing column may contain is
    not, and this is the only case of it so far. Rows written when seniority
    was free text hold "Engineering Manager" and "Lead", which no longer
    validate — the store would raise on every read of them. Idempotent: a row
    already inside the vocabulary is left alone.
    """
    rows = conn.execute(
        "SELECT id, seniority FROM job_descriptions WHERE seniority IS NOT NULL"
    ).fetchall()
    for row in rows:
        current = str(row["seniority"])
        if current in _SENIORITY_VALUES:
            continue
        replacement = _SENIORITY_FROM_TEXT.get(current.strip().lower(), "unknown")
        conn.execute(
            "UPDATE job_descriptions SET seniority = ? WHERE id = ?",
            (replacement, row["id"]),
        )


def _apply_added_columns(conn: sqlite3.Connection) -> None:
    """Add any column introduced after the table was first created."""
    for table, columns in _ADDED_COLUMNS.items():
        existing = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        for name, sql_type in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


# --------------------------------------------------------------------------- #
# Job descriptions
# --------------------------------------------------------------------------- #


def add_jd(conn: sqlite3.Connection, jd: JobDescription) -> int:
    """Insert a JD and return its new id. Ignores any id already on ``jd``."""
    salary = jd.salary_range.model_dump_json() if jd.salary_range else None
    try:
        cursor = conn.execute(
            """
            INSERT INTO job_descriptions (
                title, company, location, work_type, work_arrangement,
                salary_json, seniority, posted_by, via_agency, hiring_status,
                multiple_roles, must_haves, nice_to_haves, tech_stack,
                responsibilities, red_flags, source, source_url,
                source_metadata, raw_text, ingested_at, requisition_id,
                source_file
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                jd.title,
                jd.company,
                jd.location,
                jd.work_type.value,
                jd.work_arrangement.value,
                salary,
                jd.seniority.value,
                jd.posted_by,
                int(jd.via_agency),
                jd.hiring_status.value,
                int(jd.multiple_roles),
                json.dumps(jd.must_haves),
                json.dumps(jd.nice_to_haves),
                json.dumps(jd.tech_stack),
                json.dumps(jd.responsibilities),
                json.dumps(jd.red_flags),
                jd.source,
                jd.source_url,
                jd.source_metadata,
                jd.raw_text,
                _to_iso(jd.ingested_at),
                jd.requisition_id,
                jd.source_file,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not save job description: {exc}") from exc

    jd_id = cursor.lastrowid
    if jd_id is None:  # pragma: no cover - sqlite always sets this on insert
        raise StoreError("Insert succeeded but returned no row id")
    return jd_id


def update_jd(
    conn: sqlite3.Connection, jd_id: int, jd: JobDescription, *, amended_at: datetime
) -> str | None:
    """Replace a stored JD's parsed fields in place. Returns the text replaced.

    The id survives, which is the whole point: assessments, the application,
    its notes and its channel all hang off it, and re-adding the ad as a new
    row splits one role across two records. That happened three times in three
    days — Upgrowth 46/47, Colonial First State 27/48 — because there was no
    way to say "the same ad, with more of it".

    ``ingested_at`` is not touched. When the ad first arrived is a fact about
    the pipeline and does not change because more of it turned up later.
    """
    existing = get_jd(conn, jd_id)
    if existing is None:
        raise StoreError(f"No job description with id {jd_id}")

    salary = jd.salary_range.model_dump_json() if jd.salary_range else None
    try:
        conn.execute(
            """
            UPDATE job_descriptions SET
                title = ?, company = ?, location = ?, work_type = ?,
                work_arrangement = ?, salary_json = ?, seniority = ?,
                posted_by = ?, via_agency = ?, hiring_status = ?,
                multiple_roles = ?, must_haves = ?, nice_to_haves = ?,
                tech_stack = ?, responsibilities = ?, red_flags = ?,
                source = ?, source_url = ?, source_metadata = ?,
                raw_text = ?, amended_at = ?, superseded_text = ?,
                requisition_id = COALESCE(?, requisition_id),
                source_file = COALESCE(?, source_file),
                role_kind = NULL, role_kind_secondary = NULL,
                role_kind_reason = NULL, screen_decision = NULL,
                screen_reason = NULL, screened_at = NULL, screen_model = NULL
            WHERE id = ?
            """,
            (
                jd.title,
                jd.company,
                jd.location,
                jd.work_type.value,
                jd.work_arrangement.value,
                salary,
                jd.seniority.value,
                jd.posted_by,
                int(jd.via_agency),
                jd.hiring_status.value,
                int(jd.multiple_roles),
                json.dumps(jd.must_haves),
                json.dumps(jd.nice_to_haves),
                json.dumps(jd.tech_stack),
                json.dumps(jd.responsibilities),
                json.dumps(jd.red_flags),
                jd.source,
                jd.source_url,
                jd.source_metadata,
                jd.raw_text,
                _to_iso(amended_at),
                existing.raw_text,
                jd.requisition_id,
                jd.source_file,
                jd_id,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not amend job description {jd_id}: {exc}") from exc
    return existing.raw_text


def stale_assessments(conn: sqlite3.Connection, jd_id: int) -> int:
    """How many stored assessments predate the JD's last amendment.

    An assessment scored against text that has since been replaced is not
    wrong, it is about a different ad. Nothing deletes it — `eval` reads the
    history and a deleted row is a hole — so it is counted and reported.
    """
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM fit_assessments a
            JOIN job_descriptions j ON j.id = a.jd_id
            WHERE a.jd_id = ?
              AND j.amended_at IS NOT NULL
              AND a.scored_at < j.amended_at
            """,
            (jd_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not check assessments for {jd_id}: {exc}") from exc
    return int(row[0]) if row else 0


def latest_assessment_stale(conn: sqlite3.Connection, jd_id: int) -> bool:
    """True when the *newest* assessment predates the JD's last amendment.

    Distinct from `stale_assessments`, and the distinction is the whole point.
    The count answers "how much of this history describes an older ad", which
    is what `jd amend` should report. `score --last` shows exactly one
    assessment and must ask about that one: an older stale assessment sitting
    in the history is not a reason to warn about a fresh one. The count-based
    version shipped and fired on a re-score within the minute.
    """
    try:
        row = conn.execute(
            """
            SELECT j.amended_at, MAX(a.scored_at)
            FROM job_descriptions j
            JOIN fit_assessments a ON a.jd_id = j.id
            WHERE j.id = ?
            """,
            (jd_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not check assessments for {jd_id}: {exc}") from exc
    if row is None:
        return False
    amended_at, newest = row
    return bool(amended_at and newest and newest < amended_at)


def get_jd(conn: sqlite3.Connection, jd_id: int) -> JobDescription | None:
    """Return one JD by id, or None if there is no such row."""
    try:
        row = conn.execute(
            "SELECT * FROM job_descriptions WHERE id = ?", (jd_id,)
        ).fetchone()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not read job description {jd_id}: {exc}") from exc
    return _row_to_jd(row) if row is not None else None


def list_jds(conn: sqlite3.Connection, limit: int | None = None) -> list[JobDescription]:
    """Return JDs, newest first."""
    sql = "SELECT * FROM job_descriptions ORDER BY ingested_at DESC, id DESC"
    params: tuple = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not list job descriptions: {exc}") from exc
    return [_row_to_jd(row) for row in rows]


def list_jds_with_applications(
    conn: sqlite3.Connection,
) -> list[tuple[JobDescription, Application | None]]:
    """Every JD paired with its application, where it has one. Newest first.

    Unfiltered on purpose. Deciding which rows are the same employer is a text
    comparison — `company` is whatever the parser read off the ad, so "Nuix"
    and "Nuix Pty Ltd" are one company and no index can say so — and that rule
    belongs in Python where it can be tested. The table is two dozen rows and
    will not outgrow reading all of them.
    """
    by_jd = {app.jd_id: app for app in list_applications(conn)}
    return [(jd, by_jd.get(jd.id)) for jd in list_jds(conn)]


def delete_jd(conn: sqlite3.Connection, jd_id: int) -> bool:
    """Delete a JD. Returns True if a row was removed."""
    try:
        cursor = conn.execute("DELETE FROM job_descriptions WHERE id = ?", (jd_id,))
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not delete job description {jd_id}: {exc}") from exc
    return cursor.rowcount > 0


# --------------------------------------------------------------------------- #
# Fit assessments
# --------------------------------------------------------------------------- #


def add_assessment(conn: sqlite3.Connection, assessment: FitAssessment) -> int:
    """Insert an assessment and return its id.

    Assessments accumulate rather than replace. Re-scoring the same ad after a
    prompt change is the operation the eval harness is built on, and comparing
    the two runs is impossible if the first was overwritten.
    """
    data = assessment.model_dump(mode="json")
    try:
        cursor = conn.execute(
            """
            INSERT INTO fit_assessments (
                jd_id, overall_score, recruiter_screen_score, verdict,
                rationale, target_role_match, target_role_note, constraints,
                requirements, emphasise, challenge_points, profile_gaps,
                questions_to_ask, model_used, scored_at, contract_offer
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                assessment.jd_id,
                assessment.overall_score,
                assessment.recruiter_screen_score,
                assessment.verdict.value,
                assessment.rationale,
                int(assessment.target_role_match),
                assessment.target_role_note,
                *(json.dumps(data[column]) for column in _FIT_LIST_COLUMNS),
                assessment.model_used,
                _to_iso(assessment.scored_at),
                assessment.contract_offer,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not save fit assessment: {exc}") from exc

    assessment_id = cursor.lastrowid
    if assessment_id is None:  # pragma: no cover - sqlite always sets this
        raise StoreError("Insert succeeded but returned no row id")
    return assessment_id


def latest_assessment(
    conn: sqlite3.Connection, jd_id: int, *, model: str | None = None
) -> FitAssessment | None:
    """The most recent assessment for one JD, or None.

    ``model`` narrows it to runs from one model. Without it, a cheap run made
    to compare providers becomes the report's headline the moment it finishes,
    and the numbers change under the reader with nothing saying why.
    """
    sql = "SELECT * FROM fit_assessments WHERE jd_id = ?"
    params: tuple = (jd_id,)
    if model:
        sql += " AND model_used LIKE ?"
        params += (f"%{model}%",)
    sql += " ORDER BY scored_at DESC, id DESC LIMIT 1"
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not read assessments for JD {jd_id}: {exc}") from exc
    return _row_to_assessment(row) if row is not None else None


def list_assessments(
    conn: sqlite3.Connection, jd_id: int, *, model: str | None = None
) -> list[FitAssessment]:
    """Every assessment for one JD, newest first.

    ``model`` narrows it to runs from one model, for the same reason
    ``latest_assessment`` takes it: a cheap comparison run sitting between two
    runs of the real model turns a prompt diff into a provider diff.
    """
    sql = "SELECT * FROM fit_assessments WHERE jd_id = ?"
    params: tuple = (jd_id,)
    if model:
        sql += " AND model_used LIKE ?"
        params += (f"%{model}%",)
    sql += " ORDER BY scored_at DESC, id DESC"
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not read assessments for JD {jd_id}: {exc}") from exc
    return [_row_to_assessment(row) for row in rows]


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #


def save_application(conn: sqlite3.Connection, application: Application) -> int:
    """Insert or update the application for one JD, and return its id.

    One row per JD, replaced rather than appended: unlike an assessment, an
    application has one current truth. The history that matters — what the
    scorer said, and when — lives in ``fit_assessments``.
    """
    try:
        cursor = conn.execute(
            """
            INSERT INTO applications (
                jd_id, status, applied_on, channel, reposted_on, notes,
                worth_applying, worth_why, worth_derived, overrode_scorer,
                updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(jd_id) DO UPDATE SET
                status = excluded.status,
                applied_on = excluded.applied_on,
                channel = excluded.channel,
                reposted_on = excluded.reposted_on,
                notes = excluded.notes,
                worth_applying = excluded.worth_applying,
                worth_why = excluded.worth_why,
                worth_derived = excluded.worth_derived,
                overrode_scorer = excluded.overrode_scorer,
                updated_at = excluded.updated_at
            """,
            (
                application.jd_id,
                application.status.value,
                application.applied_on.isoformat() if application.applied_on else None,
                application.channel,
                application.reposted_on.isoformat()
                if application.reposted_on
                else None,
                application.notes,
                application.worth_applying.value,
                application.worth_why,
                int(application.worth_derived),
                int(application.overrode_scorer),
                _to_iso(application.updated_at),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not save the application: {exc}") from exc

    if cursor.lastrowid:
        return cursor.lastrowid
    existing = get_application(conn, application.jd_id)
    if existing is None or existing.id is None:  # pragma: no cover - defensive
        raise StoreError("Upsert succeeded but the row could not be read back")
    return existing.id


def get_application(conn: sqlite3.Connection, jd_id: int) -> Application | None:
    try:
        row = conn.execute(
            "SELECT * FROM applications WHERE jd_id = ?", (jd_id,)
        ).fetchone()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not read the application for JD {jd_id}: {exc}") from exc
    return _row_to_application(row) if row is not None else None


def list_applications(conn: sqlite3.Connection) -> list[Application]:
    """Every application, most recently updated first."""
    try:
        rows = conn.execute(
            "SELECT * FROM applications ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not list applications: {exc}") from exc
    return [_row_to_application(row) for row in rows]


# --------------------------------------------------------------------------- #
# Row mapping
# --------------------------------------------------------------------------- #


def _row_to_application(row: sqlite3.Row) -> Application:
    data = {
        "id": row["id"],
        "jd_id": row["jd_id"],
        "status": row["status"],
        "applied_on": row["applied_on"],
        "channel": row["channel"],
        "reposted_on": row["reposted_on"],
        "notes": row["notes"],
        "worth_applying": row["worth_applying"],
        "worth_why": row["worth_why"],
        "worth_derived": bool(row["worth_derived"]),
        "overrode_scorer": bool(row["overrode_scorer"]),
        "updated_at": row["updated_at"],
    }
    try:
        return Application.model_validate(data)
    except ValidationError as exc:
        raise StoreError(
            f"Row {row['id']} in applications no longer matches the model. "
            f"The schema changed without a migration.\n{exc}"
        ) from exc


def _row_to_assessment(row: sqlite3.Row) -> FitAssessment:
    data = {
        "id": row["id"],
        "jd_id": row["jd_id"],
        "overall_score": row["overall_score"],
        "recruiter_screen_score": row["recruiter_screen_score"],
        "verdict": row["verdict"],
        "rationale": row["rationale"],
        "target_role_match": bool(row["target_role_match"]),
        "target_role_note": row["target_role_note"],
        "model_used": row["model_used"],
        "scored_at": row["scored_at"],
        "contract_offer": row["contract_offer"],
    }
    for column in _FIT_LIST_COLUMNS:
        data[column] = _load_json_list(row, column)

    try:
        return FitAssessment.model_validate(data)
    except ValidationError as exc:
        raise StoreError(
            f"Row {row['id']} in fit_assessments no longer matches the model. "
            f"The schema changed without a migration.\n{exc}"
        ) from exc


def _row_to_jd(row: sqlite3.Row) -> JobDescription:
    data = {
        "id": row["id"],
        "title": row["title"],
        "company": row["company"],
        "location": row["location"],
        "work_type": row["work_type"],
        "work_arrangement": row["work_arrangement"],
        "salary_range": json.loads(row["salary_json"]) if row["salary_json"] else None,
        "seniority": row["seniority"],
        "posted_by": row["posted_by"],
        "via_agency": bool(row["via_agency"]),
        "hiring_status": row["hiring_status"],
        "multiple_roles": bool(row["multiple_roles"]),
        "source": row["source"],
        "source_url": row["source_url"],
        "source_metadata": row["source_metadata"],
        "raw_text": row["raw_text"],
        "ingested_at": row["ingested_at"],
        "requisition_id": row["requisition_id"],
        "source_file": row["source_file"],
    }
    for column in _LIST_COLUMNS:
        data[column] = _load_list(row, column)

    try:
        return JobDescription.model_validate(data)
    except ValidationError as exc:
        raise StoreError(
            f"Row {row['id']} in job_descriptions no longer matches the model. "
            f"The schema changed without a migration.\n{exc}"
        ) from exc


def _load_list(row: sqlite3.Row, column: str) -> list[str]:
    """A JSON column of strings. The JD's list fields are all of these."""
    return [str(item) for item in _load_json_list(row, column)]


def _load_json_list(row: sqlite3.Row, column: str) -> list:
    """A JSON column of anything. An assessment's constraints, requirements
    and challenge points are lists of objects, and stringifying them would
    turn each one into the repr of a dict."""
    raw = row[column]
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StoreError(
            f"Row {row['id']} column {column!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(value, list):
        raise StoreError(
            f"Row {row['id']} column {column!r} holds {type(value).__name__}, "
            "expected a list"
        )
    return value


def _to_iso(moment: datetime) -> str:
    """Store timestamps as UTC ISO-8601 so string ordering is time ordering."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# v10: identifiers, outside applications, reapply decisions (spec 002)
# --------------------------------------------------------------------------- #


def set_jd_identifiers(
    conn: sqlite3.Connection,
    jd_id: int,
    *,
    requisition_id: str | None = None,
    source_file: str | None = None,
) -> None:
    """Fill in either identifier on a stored ad, leaving the other as it is.

    For the backfill: neither value changes what the ad says, so this is not an
    amendment and does not touch `amended_at`.
    """
    try:
        conn.execute(
            "UPDATE job_descriptions SET "
            "requisition_id = COALESCE(?, requisition_id), "
            "source_file = COALESCE(?, source_file) WHERE id = ?",
            (requisition_id, source_file, jd_id),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not update identifiers on JD {jd_id}: {exc}") from exc


# --------------------------------------------------------------------------- #
# v11: role kind (spec 003)
# --------------------------------------------------------------------------- #


def get_role_kind(conn: sqlite3.Connection, jd_id: int) -> RoleClassification | None:
    """The stored classification, or None if the ad was never classified."""
    try:
        row = conn.execute(
            "SELECT role_kind, role_kind_secondary, role_kind_reason "
            "FROM job_descriptions WHERE id = ?",
            (jd_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not read the role kind of JD {jd_id}: {exc}") from exc
    if row is None or row["role_kind"] is None:
        return None
    return RoleClassification(
        primary=row["role_kind"],
        secondary=row["role_kind_secondary"],
        reason=row["role_kind_reason"] or "",
    )


def set_role_kind(
    conn: sqlite3.Connection, jd_id: int, classification: RoleClassification
) -> None:
    try:
        cursor = conn.execute(
            "UPDATE job_descriptions SET role_kind = ?, role_kind_secondary = ?, "
            "role_kind_reason = ? WHERE id = ?",
            (
                classification.primary.value,
                classification.secondary.value if classification.secondary else None,
                classification.reason,
                jd_id,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not store the role kind of JD {jd_id}: {exc}") from exc
    if cursor.rowcount == 0:
        raise StoreError(f"No job description with id {jd_id}")


# --------------------------------------------------------------------------- #
# v12: the first-pass screen
# --------------------------------------------------------------------------- #


def get_screen(conn: sqlite3.Connection, jd_id: int) -> dict | None:
    """{"decision", "reason", "screened_at", "model"} or None if never screened."""
    row = conn.execute(
        "SELECT screen_decision, screen_reason, screened_at, screen_model "
        "FROM job_descriptions WHERE id = ?",
        (jd_id,),
    ).fetchone()
    if row is None or row["screen_decision"] is None:
        return None
    return {
        "decision": row["screen_decision"],
        "reason": row["screen_reason"] or "",
        "screened_at": row["screened_at"],
        "model": row["screen_model"],
    }


def set_screen(
    conn: sqlite3.Connection, jd_id: int, *, decision: str, reason: str, model: str,
    at: datetime,
) -> None:
    try:
        conn.execute(
            "UPDATE job_descriptions SET screen_decision = ?, screen_reason = ?, "
            "screened_at = ?, screen_model = ? WHERE id = ?",
            (decision, reason, _to_iso(at), model, jd_id),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not store the screen of JD {jd_id}: {exc}") from exc


def add_outside(conn: sqlite3.Connection, application: OutsideApplication) -> int:
    try:
        cursor = conn.execute(
            "INSERT INTO outside_applications (company, title, requisition_id, "
            "applied_on, channel, status, notes, linked_jd_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                application.company,
                application.title,
                application.requisition_id,
                application.applied_on.isoformat(),
                application.channel,
                application.status.value,
                application.notes,
                application.linked_jd_id,
                _to_iso(application.created_at),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not save the outside application: {exc}") from exc
    return cursor.lastrowid


def list_outside(conn: sqlite3.Connection) -> list[OutsideApplication]:
    try:
        rows = conn.execute(
            "SELECT * FROM outside_applications ORDER BY applied_on DESC, id DESC"
        ).fetchall()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not list outside applications: {exc}") from exc
    return [_row_to_outside(row) for row in rows]


def get_outside(conn: sqlite3.Connection, outside_id: int) -> OutsideApplication | None:
    row = conn.execute(
        "SELECT * FROM outside_applications WHERE id = ?", (outside_id,)
    ).fetchone()
    return _row_to_outside(row) if row else None


def link_outside(conn: sqlite3.Connection, outside_id: int, jd_id: int) -> None:
    try:
        conn.execute(
            "UPDATE outside_applications SET linked_jd_id = ? WHERE id = ?",
            (jd_id, outside_id),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not link outside application {outside_id}: {exc}") from exc


def get_reapply_decision(conn: sqlite3.Connection, jd_id: int) -> ReapplyDecision | None:
    row = conn.execute(
        "SELECT * FROM reapply_decisions WHERE jd_id = ?", (jd_id,)
    ).fetchone()
    if row is None:
        return None
    return ReapplyDecision(
        jd_id=row["jd_id"],
        decision=row["decision"],
        matched=row["matched"],
        decided_at=row["decided_at"],
    )


def set_reapply_decision(conn: sqlite3.Connection, decision: ReapplyDecision) -> None:
    """Record or replace the one decision held for an ad."""
    try:
        conn.execute(
            "INSERT INTO reapply_decisions (jd_id, decision, matched, decided_at) "
            "VALUES (?,?,?,?) ON CONFLICT(jd_id) DO UPDATE SET "
            "decision = excluded.decision, matched = excluded.matched, "
            "decided_at = excluded.decided_at",
            (decision.jd_id, decision.decision, decision.matched, _to_iso(decision.decided_at)),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not record the decision for JD {decision.jd_id}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Sent documents
# --------------------------------------------------------------------------- #


def add_sent(conn: sqlite3.Connection, document: SentDocument) -> int:
    try:
        cursor = conn.execute(
            "INSERT INTO sent_documents (jd_id, kind, folder, name, sha256, "
            "generated, as_generated, sent_on, recorded_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                document.jd_id,
                document.kind.value,
                document.folder,
                document.name,
                document.sha256,
                document.generated,
                int(document.as_generated),
                document.sent_on.isoformat(),
                _to_iso(document.recorded_at),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not record the sent document: {exc}") from exc
    return cursor.lastrowid


def move_sent_folder(conn: sqlite3.Connection, old: str, new: str) -> None:
    """Follow a folder `supersede` moved aside: the sent copies moved with it."""
    try:
        conn.execute("UPDATE sent_documents SET folder = ? WHERE folder = ?", (new, old))
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not follow {old} to {new}: {exc}") from exc


def list_sent(conn: sqlite3.Connection, jd_id: int | None = None) -> list[SentDocument]:
    """Sent documents, oldest first; every ad's when `jd_id` is None."""
    sql = "SELECT * FROM sent_documents"
    params: tuple = ()
    if jd_id is not None:
        sql += " WHERE jd_id = ?"
        params = (jd_id,)
    try:
        rows = conn.execute(sql + " ORDER BY sent_on, id", params).fetchall()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not list sent documents: {exc}") from exc
    return [
        SentDocument(
            id=row["id"],
            jd_id=row["jd_id"],
            kind=row["kind"],
            folder=row["folder"],
            name=row["name"],
            sha256=row["sha256"],
            generated=row["generated"],
            as_generated=bool(row["as_generated"]),
            sent_on=row["sent_on"],
            recorded_at=row["recorded_at"],
        )
        for row in rows
    ]


# --------------------------------------------------------------------------- #
# v14: context and revision notes
# --------------------------------------------------------------------------- #


def get_context(conn: sqlite3.Connection, jd_id: int) -> str | None:
    row = conn.execute("SELECT text FROM ad_context WHERE jd_id = ?", (jd_id,)).fetchone()
    return row["text"] if row else None


def set_context(conn: sqlite3.Connection, jd_id: int, text: str | None, now: datetime) -> None:
    """Replace the ad's context; empty or None removes it."""
    try:
        if text and text.strip():
            conn.execute(
                "INSERT INTO ad_context (jd_id, text, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(jd_id) DO UPDATE SET text = excluded.text, "
                "updated_at = excluded.updated_at",
                (jd_id, text.strip(), _to_iso(now)),
            )
        else:
            conn.execute("DELETE FROM ad_context WHERE jd_id = ?", (jd_id,))
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not save the context for JD {jd_id}: {exc}") from exc


def add_revision_note(conn: sqlite3.Connection, note: RevisionNote) -> int:
    try:
        cursor = conn.execute(
            "INSERT INTO revision_notes (jd_id, kind, note, created_at, result) VALUES (?,?,?,?,?)",
            (note.jd_id, note.kind.value, note.note, _to_iso(note.created_at), note.result),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not record the revision note: {exc}") from exc
    return cursor.lastrowid


def set_revision_result(conn: sqlite3.Connection, note_id: int, result: str) -> None:
    try:
        conn.execute("UPDATE revision_notes SET result = ? WHERE id = ?", (result, note_id))
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not update revision note {note_id}: {exc}") from exc


def list_revision_notes(conn: sqlite3.Connection, jd_id: int | None = None) -> list[RevisionNote]:
    """Oldest first; every ad's when `jd_id` is None."""
    sql, params = "SELECT * FROM revision_notes", ()
    if jd_id is not None:
        sql, params = sql + " WHERE jd_id = ?", (jd_id,)
    try:
        rows = conn.execute(sql + " ORDER BY created_at, id", params).fetchall()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not list revision notes: {exc}") from exc
    return [
        RevisionNote(
            id=row["id"], jd_id=row["jd_id"], kind=row["kind"], note=row["note"],
            created_at=row["created_at"], result=row["result"],
        )
        for row in rows
    ]


def _row_to_outside(row: sqlite3.Row) -> OutsideApplication:
    return OutsideApplication(
        id=row["id"],
        company=row["company"],
        title=row["title"],
        requisition_id=row["requisition_id"],
        applied_on=row["applied_on"],
        channel=row["channel"],
        status=row["status"],
        notes=row["notes"],
        linked_jd_id=row["linked_jd_id"],
        created_at=row["created_at"],
    )


# --------------------------------------------------------------------------- #
# v16: contacts
# --------------------------------------------------------------------------- #


def add_contact(conn: sqlite3.Connection, contact: Contact) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO contacts (name, firm, kind, specialty, channel, first_contact, "
            "last_touch, next_followup, notes, jd_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                contact.name, contact.firm, contact.kind.value, contact.specialty,
                contact.channel, contact.first_contact.isoformat(),
                contact.last_touch.isoformat(),
                contact.next_followup.isoformat() if contact.next_followup else None,
                contact.notes, contact.jd_id, contact.created_at.isoformat(),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not save the contact: {exc}") from exc
    return int(cur.lastrowid)


def get_contact(conn: sqlite3.Connection, contact_id: int) -> Contact | None:
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    return _row_to_contact(row) if row else None


def list_contacts(conn: sqlite3.Connection) -> list[Contact]:
    """Soonest follow-up first; contacts with none last."""
    try:
        rows = conn.execute(
            "SELECT * FROM contacts ORDER BY next_followup IS NULL, next_followup, name"
        ).fetchall()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not list contacts: {exc}") from exc
    return [_row_to_contact(row) for row in rows]


def update_contact(conn: sqlite3.Connection, contact: Contact) -> None:
    """Write back the fields that change after a contact is added."""
    try:
        conn.execute(
            "UPDATE contacts SET last_touch = ?, next_followup = ?, notes = ?, jd_id = ? "
            "WHERE id = ?",
            (
                contact.last_touch.isoformat(),
                contact.next_followup.isoformat() if contact.next_followup else None,
                contact.notes, contact.jd_id, contact.id,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not update contact {contact.id}: {exc}") from exc


def _row_to_contact(row: sqlite3.Row) -> Contact:
    return Contact(
        id=row["id"], name=row["name"], firm=row["firm"], kind=row["kind"],
        specialty=row["specialty"], channel=row["channel"],
        first_contact=row["first_contact"], last_touch=row["last_touch"],
        next_followup=row["next_followup"], notes=row["notes"], jd_id=row["jd_id"],
        created_at=row["created_at"],
    )


# --------------------------------------------------------------------------- #
# v17: job-alert listings
# --------------------------------------------------------------------------- #


def get_alert(conn: sqlite3.Connection, listing_id: int) -> AlertListing | None:
    row = conn.execute("SELECT * FROM alert_listings WHERE id = ?", (listing_id,)).fetchone()
    return _row_to_alert(row) if row else None


def find_alert(conn: sqlite3.Connection, source: str, job_id: str) -> AlertListing | None:
    row = conn.execute(
        "SELECT * FROM alert_listings WHERE source = ? AND job_id = ?", (source, job_id)
    ).fetchone()
    return _row_to_alert(row) if row else None


def list_alerts(conn: sqlite3.Connection) -> list[AlertListing]:
    """Newest first."""
    try:
        rows = conn.execute("SELECT * FROM alert_listings ORDER BY first_seen DESC, id DESC").fetchall()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not list alert listings: {exc}") from exc
    return [_row_to_alert(row) for row in rows]


def save_alert(conn: sqlite3.Connection, a: AlertListing) -> int:
    """Insert a new listing or update an existing one by id."""
    values = (
        a.source, a.job_id, a.title, a.company, a.location, a.pay, a.url,
        a.first_seen.isoformat(), a.last_seen.isoformat(), a.times_seen,
        a.verdict.value, a.reason, a.decision.value if a.decision else None,
        a.decided_at.isoformat() if a.decided_at else None, a.note, a.jd_id, a.saved_file,
    )
    try:
        if a.id is None:
            cur = conn.execute(
                "INSERT INTO alert_listings (source, job_id, title, company, location, pay, url, "
                "first_seen, last_seen, times_seen, verdict, reason, decision, decided_at, note, jd_id, "
                "saved_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            a.id = int(cur.lastrowid)
        else:
            conn.execute(
                "UPDATE alert_listings SET source = ?, job_id = ?, title = ?, company = ?, "
                "location = ?, pay = ?, url = ?, first_seen = ?, last_seen = ?, times_seen = ?, "
                "verdict = ?, reason = ?, decision = ?, decided_at = ?, note = ?, jd_id = ?, "
                "saved_file = ? WHERE id = ?",
                (*values, a.id),
            )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not save alert listing: {exc}") from exc
    return a.id


def _row_to_alert(row: sqlite3.Row) -> AlertListing:
    return AlertListing(
        id=row["id"], source=row["source"], job_id=row["job_id"], title=row["title"],
        company=row["company"], location=row["location"], pay=row["pay"], url=row["url"],
        first_seen=row["first_seen"], last_seen=row["last_seen"], times_seen=row["times_seen"],
        verdict=row["verdict"], reason=row["reason"], decision=row["decision"],
        decided_at=row["decided_at"], note=row["note"], jd_id=row["jd_id"],
        saved_file=row["saved_file"],
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    try:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not save {key}: {exc}") from exc


def alert_email_read(conn: sqlite3.Connection, message_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM alert_emails WHERE message_id = ?", (message_id,)
    ).fetchone() is not None


def mark_alert_email(conn: sqlite3.Connection, message_id: str, read_at: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO alert_emails (message_id, read_at) VALUES (?, ?)", (message_id, read_at)
    )
    conn.commit()


def scanned_file(conn: sqlite3.Connection, name: str) -> tuple[int, str | None, str | None] | None:
    row = conn.execute("SELECT mtime_ns, source, job_id FROM scanned_files WHERE name = ?", (name,)).fetchone()
    return (row["mtime_ns"], row["source"], row["job_id"]) if row else None


def record_scanned_file(conn: sqlite3.Connection, name: str, mtime_ns: int, key: tuple[str, str] | None) -> None:
    conn.execute(
        "INSERT INTO scanned_files (name, mtime_ns, source, job_id) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET mtime_ns = excluded.mtime_ns, source = excluded.source, "
        "job_id = excluded.job_id",
        (name, mtime_ns, key[0] if key else None, key[1] if key else None),
    )
    conn.commit()
