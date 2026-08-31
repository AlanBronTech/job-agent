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

from jobagent.core.models import JobDescription

SCHEMA_VERSION = 2

# Columns added after v1. CREATE TABLE IF NOT EXISTS will not add a column to a
# table that already exists, so additive changes are applied explicitly. This is
# not a migration framework and is not pretending to be one: it handles the only
# kind of change that is safe to make without one.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "job_descriptions": [
        ("source_url", "TEXT"),
        ("source_metadata", "TEXT"),
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
    seniority        TEXT,
    must_haves       TEXT NOT NULL DEFAULT '[]',
    nice_to_haves    TEXT NOT NULL DEFAULT '[]',
    tech_stack       TEXT NOT NULL DEFAULT '[]',
    responsibilities TEXT NOT NULL DEFAULT '[]',
    red_flags        TEXT NOT NULL DEFAULT '[]',
    source           TEXT,
    source_url       TEXT,
    source_metadata  TEXT,
    raw_text         TEXT NOT NULL,
    ingested_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jd_company ON job_descriptions (company);
CREATE INDEX IF NOT EXISTS idx_jd_ingested ON job_descriptions (ingested_at);
"""

_LIST_COLUMNS = (
    "must_haves",
    "nice_to_haves",
    "tech_stack",
    "responsibilities",
    "red_flags",
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
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not initialise schema: {exc}") from exc


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
                salary_json, seniority, must_haves, nice_to_haves, tech_stack,
                responsibilities, red_flags, source, source_url,
                source_metadata, raw_text, ingested_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                jd.title,
                jd.company,
                jd.location,
                jd.work_type.value,
                jd.work_arrangement.value,
                salary,
                jd.seniority,
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


def delete_jd(conn: sqlite3.Connection, jd_id: int) -> bool:
    """Delete a JD. Returns True if a row was removed."""
    try:
        cursor = conn.execute("DELETE FROM job_descriptions WHERE id = ?", (jd_id,))
        conn.commit()
    except sqlite3.Error as exc:
        raise StoreError(f"Could not delete job description {jd_id}: {exc}") from exc
    return cursor.rowcount > 0


# --------------------------------------------------------------------------- #
# Row mapping
# --------------------------------------------------------------------------- #


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
    return [str(item) for item in value]


def _to_iso(moment: datetime) -> str:
    """Store timestamps as UTC ISO-8601 so string ordering is time ordering."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()
