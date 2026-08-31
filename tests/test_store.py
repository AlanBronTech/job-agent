"""Unit tests for SQLite persistence. No LLM, no network."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from jobagent.core import store
from jobagent.core.models import (
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
        "seniority": "Manager",
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
