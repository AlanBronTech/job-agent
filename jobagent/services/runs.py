"""The UI's record of actions it has started: running, finished, seen.

A run outlives the page that started it (FR-016a), so its state cannot live in
the browser, and it must survive a restart well enough to say "interrupted"
rather than "still running" or nothing at all (FR-016b). One row per action —
a parse, a score, a generate, a prep. The model calls themselves stay in
`runs.jsonl`, joined on `run_id`.

The table belongs to this module, not to `core/store.py`, and does not move
`SCHEMA_VERSION`: it is UI state, and Constitution II keeps UI needs out of
`core/` (analysis C1, 2026-09-30). It is created on first use.

`result` is only ever a copy of what a service returned and the page already
showed. Losing it loses nothing that is not in the store or on disk.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from jobagent.core import store
from jobagent.services.refusals import RunInProgress
from jobagent.services.workspace import Workspace

KINDS = ("add_ad", "score", "generate", "prep")
STATUSES = ("running", "succeeded", "failed", "interrupted")

_DDL = """
CREATE TABLE IF NOT EXISTS ui_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner       TEXT NOT NULL DEFAULT 'local',
    jd_id       INTEGER REFERENCES job_descriptions (id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('add_ad', 'score', 'generate', 'prep')),
    status      TEXT NOT NULL
                    CHECK (status IN ('running', 'succeeded', 'failed', 'interrupted')),
    run_id      TEXT NOT NULL,
    request     TEXT NOT NULL DEFAULT '{}',
    result      TEXT,
    error       TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    seen_at     TEXT
);

-- Backstop for FR-006. The check-and-insert in start_run is the real guard.
CREATE UNIQUE INDEX IF NOT EXISTS idx_ui_runs_one_running
    ON ui_runs (jd_id) WHERE status = 'running';
"""


@dataclass
class Run:
    id: int
    owner: str
    jd_id: int | None
    kind: str
    status: str
    run_id: str
    request: dict
    result: dict | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    seen_at: datetime | None

    @property
    def finished(self) -> bool:
        return self.status != "running"


def start_run(
    ws: Workspace, *, kind: str, jd_id: int | None, run_id: str, request: dict
) -> int:
    """Record a run as started, or raise RunInProgress pointing at the one already going.

    The check and the insert happen inside one `BEGIN IMMEDIATE`, which takes
    the write lock before reading, so two clicks arriving together cannot both
    see "nothing running" and both start. An `add_ad` has no ad id yet, so it is
    keyed on what is being parsed: the file name, or a hash of pasted text.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown run kind {kind!r}")
    with _open(ws) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = _running_for(conn, ws.owner, kind, jd_id, request)
            if existing is not None:
                raise RunInProgress(existing)
            cursor = conn.execute(
                "INSERT INTO ui_runs (owner, jd_id, kind, status, run_id, request, started_at) "
                "VALUES (?, ?, ?, 'running', ?, ?, ?)",
                (ws.owner, jd_id, kind, run_id, json.dumps(request), _now()),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return cursor.lastrowid


def finish_run(
    ws: Workspace,
    run: int,
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
    jd_id: int | None = None,
) -> None:
    """Record how a run ended. `jd_id` fills in the ad an `add_ad` created."""
    if status not in STATUSES or status == "running":
        raise ValueError(f"not a finishing status: {status!r}")
    with _open(ws) as conn:
        conn.execute(
            "UPDATE ui_runs SET status = ?, result = ?, error = ?, finished_at = ?, "
            "jd_id = COALESCE(?, jd_id) WHERE id = ?",
            (status, json.dumps(result) if result is not None else None, error, _now(), jd_id, run),
        )
        conn.commit()


def get_run(ws: Workspace, run: int) -> Run | None:
    with _open(ws) as conn:
        row = conn.execute(
            "SELECT * FROM ui_runs WHERE id = ? AND owner = ?", (run, ws.owner)
        ).fetchone()
    return _row(row) if row else None


def active_run_for(ws: Workspace, jd_id: int) -> Run | None:
    with _open(ws) as conn:
        row = conn.execute(
            "SELECT * FROM ui_runs WHERE owner = ? AND jd_id = ? AND status = 'running' "
            "ORDER BY id DESC LIMIT 1",
            (ws.owner, jd_id),
        ).fetchone()
    return _row(row) if row else None


def last_run_for(ws: Workspace, jd_id: int, kind: str | None = None) -> Run | None:
    sql = "SELECT * FROM ui_runs WHERE owner = ? AND jd_id = ?"
    params: tuple = (ws.owner, jd_id)
    if kind:
        sql += " AND kind = ?"
        params += (kind,)
    with _open(ws) as conn:
        row = conn.execute(sql + " ORDER BY id DESC LIMIT 1", params).fetchone()
    return _row(row) if row else None


def unseen_finished(ws: Workspace) -> list[Run]:
    """Finished runs nobody has looked at yet: the banner on every page."""
    with _open(ws) as conn:
        rows = conn.execute(
            "SELECT * FROM ui_runs WHERE owner = ? AND status != 'running' "
            "AND seen_at IS NULL ORDER BY id",
            (ws.owner,),
        ).fetchall()
    return [_row(r) for r in rows]


def mark_seen(ws: Workspace, run: int) -> None:
    with _open(ws) as conn:
        conn.execute(
            "UPDATE ui_runs SET seen_at = ? WHERE id = ? AND owner = ? "
            "AND status != 'running' AND seen_at IS NULL",
            (_now(), run, ws.owner),
        )
        conn.commit()


def mark_seen_for_jd(ws: Workspace, jd_id: int) -> None:
    """Opening an ad's page is seeing every finished run on it."""
    with _open(ws) as conn:
        conn.execute(
            "UPDATE ui_runs SET seen_at = ? WHERE owner = ? AND jd_id = ? "
            "AND status != 'running' AND seen_at IS NULL",
            (_now(), ws.owner, jd_id),
        )
        conn.commit()


def interrupt_running(ws: Workspace) -> int:
    """At server start, anything still `running` died with the last server.

    Every owner, not just this workspace's: one process serves the database,
    so a run it did not finish cannot be alive anywhere.
    """
    with _open(ws) as conn:
        cursor = conn.execute(
            "UPDATE ui_runs SET status = 'interrupted', finished_at = ? "
            "WHERE status = 'running'",
            (_now(),),
        )
        conn.commit()
        return cursor.rowcount


# --------------------------------------------------------------------------- #


def _open(ws: Workspace):
    return _Conn(ws)


class _Conn:
    """`store.open_store` plus this module's table."""

    def __init__(self, ws: Workspace) -> None:
        self._cm = store.open_store(ws.db_path)

    def __enter__(self) -> sqlite3.Connection:
        conn = self._cm.__enter__()
        conn.executescript(_DDL)
        return conn

    def __exit__(self, *exc) -> None:
        self._cm.__exit__(*exc)


def _running_for(conn, owner, kind, jd_id, request) -> int | None:
    if jd_id is not None:
        row = conn.execute(
            "SELECT id FROM ui_runs WHERE owner = ? AND jd_id = ? AND status = 'running'",
            (owner, jd_id),
        ).fetchone()
        return row["id"] if row else None
    key = request.get("input_key")
    if kind == "add_ad" and key:
        for row in conn.execute(
            "SELECT id, request FROM ui_runs WHERE owner = ? AND kind = 'add_ad' "
            "AND status = 'running'",
            (owner,),
        ):
            if json.loads(row["request"]).get("input_key") == key:
                return row["id"]
    return None


def _row(row: sqlite3.Row) -> Run:
    return Run(
        id=row["id"],
        owner=row["owner"],
        jd_id=row["jd_id"],
        kind=row["kind"],
        status=row["status"],
        run_id=row["run_id"],
        request=json.loads(row["request"] or "{}"),
        result=json.loads(row["result"]) if row["result"] else None,
        error=row["error"],
        started_at=_parse(row["started_at"]),
        finished_at=_parse(row["finished_at"]),
        seen_at=_parse(row["seen_at"]),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
