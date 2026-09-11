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

from jobagent.core.models import Application, FitAssessment, JobDescription

SCHEMA_VERSION = 9

# Columns added after v1. CREATE TABLE IF NOT EXISTS will not add a column to a
# table that already exists, so additive changes are applied explicitly. This is
# not a migration framework and is not pretending to be one: it handles the only
# kind of change that is safe to make without one.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
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
    superseded_text  TEXT
);

CREATE INDEX IF NOT EXISTS idx_jd_company ON job_descriptions (company);
CREATE INDEX IF NOT EXISTS idx_jd_ingested ON job_descriptions (ingested_at);

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
                source_metadata, raw_text, ingested_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                raw_text = ?, amended_at = ?, superseded_text = ?
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
                questions_to_ask, model_used, scored_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
