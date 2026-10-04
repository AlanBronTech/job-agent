"""Batch review: every saved ad taken in at once, one row per file.

The point is the row per file. In the batch this was built from, a capture cut
off at "…more" was refused inside another ad's output and was only noticed
when the table was compared against the folder. Here a refused file is its own
row, with the reason and what to do (spec 002, FR-002, SC-003).

Every paid step is the single-ad action (`ads.add`, and scoring is called per
row by the front ends), so a batch inherits every guard. The tables here hold
only what nothing else records: which files a batch covered, and why a file was
refused. Everything else a row shows is derived from the store and the disk.

New files are those saved after a baseline, so the whole folder is never
offered at once: the start of the first batch, or, before any batch exists,
the moment the latest ad was added.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from jobagent.adapters.llm import RunContext
from jobagent.core import history, store
from jobagent.core.jd import JDError
from jobagent.core.profile import ProfileError, load_profile
from jobagent.core.requisition import normalise_requisition
from jobagent.core.scoring import check_constraints
from jobagent.services import ads, outputs, reapply
from jobagent.services.refusals import NoModel, UnreadableAd
from jobagent.services.workspace import Workspace

_DDL = """
CREATE TABLE IF NOT EXISTS batches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner      TEXT NOT NULL DEFAULT 'local',
    started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_rows (
    batch_id       INTEGER NOT NULL REFERENCES batches (id) ON DELETE CASCADE,
    file_name      TEXT NOT NULL,
    jd_id          INTEGER REFERENCES job_descriptions (id) ON DELETE SET NULL,
    refusal        TEXT,
    refusal_detail TEXT,
    PRIMARY KEY (batch_id, file_name)
);
"""

# Refusal codes stored on a row; `describe` words them for both front ends.
TRUNCATED, UNREADABLE, MISSING, DUPLICATE, PARSE_FAILED, NO_MODEL = (
    "truncated", "unreadable", "missing", "duplicate", "parse_failed", "no_model",
)


@dataclass
class BatchRow:
    number: int
    file_name: str
    jd_id: int | None
    state: str  # refused | waiting | parsed | scored | documents | <application status>
    refusal: str | None = None
    refusal_detail: str | None = None
    company: str | None = None
    title: str | None = None
    arrangement: str | None = None
    salary: str | None = None
    posting: str | None = None
    requisition_id: str | None = None
    filters: list[tuple[str, str]] = field(default_factory=list)  # (name, ok|breach|unknown|note)
    history_count: int = 0
    reapply: str = "clear"  # clear | same | possibly_same
    same_requisition_as: int | None = None
    verdict: str | None = None
    overall_score: int | None = None
    recruiter_score: int | None = None
    has_documents: bool = False
    status: str | None = None


def describe(code: str, detail: str | None) -> str:
    """Why a file was refused, and what to do next. One wording for CLI and UI."""
    return {
        TRUNCATED: "Cut off at '…more'. Expand the description on the page, save it again, then parse the batch.",
        UNREADABLE: f"Could not be read: {detail}.",
        MISSING: "No longer in the saved-ads folder.",
        DUPLICATE: f"The same text as JD {detail}, already stored. Not parsed.",
        PARSE_FAILED: f"The parse failed: {detail}. Parse the batch again to retry.",
        NO_MODEL: f"No model available: {detail}.",
    }.get(code, detail or code)


# --------------------------------------------------------------------------- #


def baseline(ws: Workspace) -> datetime | None:
    with _open(ws) as conn:
        row = conn.execute(
            "SELECT MIN(started_at) FROM batches WHERE owner = ?", (ws.owner,)
        ).fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        row = conn.execute("SELECT MAX(ingested_at) FROM job_descriptions").fetchone()
    return datetime.fromisoformat(row[0]) if row and row[0] else None


def new_files(ws: Workspace) -> list[Path]:
    """Saved ads not yet taken in, oldest first. Free."""
    since = baseline(ws)
    with _open(ws) as conn:
        taken = {
            r[0] for r in conn.execute(
                "SELECT source_file FROM job_descriptions WHERE source_file IS NOT NULL"
            )
        }
        last_row = {
            r["file_name"]: r
            for r in conn.execute(
                "SELECT r.file_name, r.jd_id, r.refusal, b.started_at FROM batch_rows r "
                "JOIN batches b ON b.id = r.batch_id WHERE b.owner = ? ORDER BY b.id",
                (ws.owner,),
            )
        }
    found = []
    for path in ads.ads_in(ws.jd_dir):
        if path.name in taken:
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if since is not None and modified <= _aware(since):
            continue
        previous = last_row.get(path.name)
        if previous is not None:
            if previous["jd_id"] is not None or previous["refusal"] == DUPLICATE:
                continue
            # Refused before: offered again only once the file has been saved again.
            if modified <= _aware(datetime.fromisoformat(previous["started_at"])):
                continue
        found.append(path)
    return sorted(found, key=lambda p: p.stat().st_mtime)


def start(ws: Workspace, now: datetime | None = None) -> int | None:
    """A new batch over the new files. None when there is nothing new."""
    files = new_files(ws)
    if not files:
        return None
    with _open(ws) as conn:
        cursor = conn.execute(
            "INSERT INTO batches (owner, started_at) VALUES (?, ?)",
            (ws.owner, (now or datetime.now(timezone.utc)).isoformat()),
        )
        batch_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO batch_rows (batch_id, file_name) VALUES (?, ?)",
            [(batch_id, p.name) for p in files],
        )
        conn.commit()
    return batch_id


def latest(ws: Workspace) -> int | None:
    with _open(ws) as conn:
        row = conn.execute(
            "SELECT MAX(id) FROM batches WHERE owner = ?", (ws.owner,)
        ).fetchone()
    return row[0] if row and row[0] else None


def waiting(ws: Workspace, batch_id: int) -> list[str]:
    """Files a parse would spend on: not yet parsed, and not refused for a reason
    that another try cannot fix. A failed parse or a missing model is retried."""
    with _open(ws) as conn:
        return [
            r[0] for r in conn.execute(
                "SELECT file_name FROM batch_rows WHERE batch_id = ? AND jd_id IS NULL "
                "AND (refusal IS NULL OR refusal IN (?, ?)) ORDER BY rowid",
                (batch_id, PARSE_FAILED, NO_MODEL),
            )
        ]


def parse(
    ws: Workspace,
    config,
    batch_id: int,
    *,
    source: str = "cli",
    client_factory=None,
    before_spend=None,
) -> None:
    """Parse every waiting file through `ads.add`. Resumable: done rows are skipped.

    Free refusals (cut off, unreadable, already stored) are recorded before any
    spend. `before_spend` runs once, before the first paid parse.
    """
    spent = False
    for name in waiting(ws, batch_id):
        path = ws.jd_dir / name
        if not path.is_file():
            _refuse(ws, batch_id, name, MISSING, None)
            continue
        try:
            ad = ads.read_ad(file=path)
        except UnreadableAd as exc:
            _refuse(ws, batch_id, name, UNREADABLE, exc.detail)
            continue
        if ad.truncated:
            _refuse(ws, batch_id, name, TRUNCATED, None)
            continue
        duplicate = _stored_with_text(ws, ad.raw_text)
        if duplicate is not None:
            _refuse(ws, batch_id, name, DUPLICATE, str(duplicate))
            continue
        if not spent and before_spend is not None:
            before_spend()
        spent = True
        context = RunContext(command="jd add", source=source)
        try:
            result = ads.add(
                ws, config, context, ad,
                client=client_factory(context) if client_factory else None,
            )
        except NoModel as exc:
            _refuse(ws, batch_id, name, NO_MODEL, exc.detail)
            continue
        except (JDError, store.StoreError) as exc:
            _refuse(ws, batch_id, name, PARSE_FAILED, str(exc))
            continue
        with _open(ws) as conn:
            conn.execute(
                "UPDATE batch_rows SET jd_id = ?, refusal = NULL, refusal_detail = NULL "
                "WHERE batch_id = ? AND file_name = ?",
                (result.jd.id, batch_id, name),
            )
            conn.commit()


def rows(ws: Workspace, batch_id: int, today: date) -> list[BatchRow]:
    """The table: one row per file, everything but refusals derived. Free."""
    try:
        profile = load_profile(ws.profile_dir) if ws.profile_dir else None
    except ProfileError:
        profile = None
    with _open(ws) as conn:
        raw = conn.execute(
            "SELECT file_name, jd_id, refusal, refusal_detail FROM batch_rows "
            "WHERE batch_id = ? ORDER BY rowid",
            (batch_id,),
        ).fetchall()
        result: list[BatchRow] = []
        for number, r in enumerate(raw, start=1):
            row = BatchRow(number=number, file_name=r["file_name"], jd_id=r["jd_id"],
                           state="refused" if r["refusal"] else "waiting",
                           refusal=r["refusal"], refusal_detail=r["refusal_detail"])
            jd = store.get_jd(conn, r["jd_id"]) if r["jd_id"] else None
            if jd is not None:
                _fill(conn, ws, row, jd, profile, today)
            result.append(row)
    _flag_shared_requisitions(result)
    return result


# --------------------------------------------------------------------------- #


def _fill(conn, ws, row: BatchRow, jd, profile, today: date) -> None:
    row.state = "parsed"
    row.company, row.title, row.requisition_id = jd.company, jd.title, jd.requisition_id
    row.arrangement = f"{jd.work_arrangement.value} · {jd.work_type.value}"
    row.salary = jd.salary_range.raw if jd.salary_range and jd.salary_range.raw else None
    row.posting = jd.source_metadata
    if profile is not None:
        row.filters = [
            (c.name, "note" if c.advisory else c.status.value) for c in check_constraints(jd, profile)
        ]
    row.history_count = len(history.company_history(conn, jd).encounters)
    row.reapply = reapply.check(ws, jd.id, today).kind
    assessment = store.latest_assessment(conn, jd.id)
    if assessment is not None:
        row.state = "scored"
        row.verdict = assessment.verdict.value
        row.overall_score = assessment.overall_score
        row.recruiter_score = assessment.recruiter_screen_score
    row.has_documents = outputs.documents_for(ws, jd, today).any
    if row.has_documents:
        row.state = "documents"
    application = store.get_application(conn, jd.id)
    if application is not None:
        row.status = application.status.value
        row.state = application.status.value


def _flag_shared_requisitions(result: list[BatchRow]) -> None:
    keys = Counter(normalise_requisition(r.requisition_id) for r in result if r.requisition_id)
    first: dict[str, int] = {}
    for r in result:
        if not r.requisition_id:
            continue
        key = normalise_requisition(r.requisition_id)
        if keys[key] > 1:
            if key in first:
                r.same_requisition_as = first[key]
            else:
                first[key] = r.number
                r.same_requisition_as = None


def _stored_with_text(ws: Workspace, text: str) -> int | None:
    with _open(ws) as conn:
        row = conn.execute(
            "SELECT id FROM job_descriptions WHERE raw_text = ? ORDER BY id LIMIT 1", (text,)
        ).fetchone()
    return row[0] if row else None


def _refuse(ws: Workspace, batch_id: int, name: str, code: str, detail: str | None) -> None:
    with _open(ws) as conn:
        conn.execute(
            "UPDATE batch_rows SET refusal = ?, refusal_detail = ? "
            "WHERE batch_id = ? AND file_name = ?",
            (code, detail, batch_id, name),
        )
        conn.commit()


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class _open:
    """`store.open_store` plus this module's tables, created on first use."""

    def __init__(self, ws: Workspace) -> None:
        self._cm = store.open_store(ws.db_path)

    def __enter__(self) -> sqlite3.Connection:
        conn = self._cm.__enter__()
        conn.executescript(_DDL)
        return conn

    def __exit__(self, *exc) -> None:
        self._cm.__exit__(*exc)
