"""Saved ads leave the drop folder once JobAgent no longer needs the file.

An added ad's full text is in `job_descriptions.raw_text`; parsing again,
`jd amend`, prep and the six-month rule all read it from there, never from
the file (Alan, 2026-11-19). So a file is moved to the bin when its job
closes without success, or 30 days after it was added, whichever is first.

Only a file a stored ad names as its `source_file` is ever moved. A file that
was never added is not in the database at all, so an old one is listed for
Alan to decide on, not binned. OUTPUT_DIR is never touched here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from jobagent.adapters.trash import TrashError, move_to_trash
from jobagent.core import store
from jobagent.core.models import ApplicationStatus
from jobagent.services.ads import ads_in
from jobagent.services.workspace import Workspace

KEEP_DAYS = 30

# Closed, and not in his favour. `withdrew` is his choice, not an outcome; the
# 30-day rule takes those files anyway.
UNSUCCESSFUL = frozenset({
    ApplicationStatus.not_applied,
    ApplicationStatus.applied_no_reply,
    ApplicationStatus.rejected_screen,
    ApplicationStatus.rejected_after_interview,
    ApplicationStatus.ghosted_after_contact,
})


@dataclass
class Binned:
    name: str
    jd_id: int
    reason: str


@dataclass
class Sweep:
    binned: list[Binned] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    # Older than KEEP_DAYS and never added: not in the database, so kept.
    not_added: list[str] = field(default_factory=list)


def due(ws: Workspace, now: datetime) -> Sweep:
    """What a sweep would move, and the old files it would leave. Moves nothing."""
    cutoff = now - timedelta(days=KEEP_DAYS)
    linked: dict[str, list[tuple[int, datetime, ApplicationStatus | None]]] = {}
    with store.open_store(ws.db_path) as conn:
        for row in conn.execute(
            "SELECT j.id, j.source_file, j.ingested_at, a.status FROM job_descriptions j "
            "LEFT JOIN applications a ON a.jd_id = j.id WHERE j.source_file IS NOT NULL"
        ):
            status = ApplicationStatus(row[3]) if row[3] else None
            linked.setdefault(row[1], []).append((row[0], _when(row[2]), status))

    plan = Sweep()
    for path in ads_in(ws.jd_dir):
        rows = linked.get(path.name)
        if not rows:
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
                plan.not_added.append(path.name)
            continue
        reason = _reason(rows, cutoff)
        if reason:
            plan.binned.append(Binned(path.name, *reason))
    return plan


def sweep(ws: Workspace, now: datetime, *, dry_run: bool = False) -> Sweep:
    """Move every file that is due to the bin. Free; a failed move is reported, not raised."""
    plan = due(ws, now)
    if dry_run:
        return plan
    if ws.trash_dir is None:
        return Sweep(not_added=plan.not_added)
    done = Sweep(not_added=plan.not_added)
    for item in plan.binned:
        try:
            move_to_trash(ws.jd_dir / item.name, ws.trash_dir)
        except TrashError as exc:
            done.failed.append((item.name, str(exc)))
            continue
        done.binned.append(item)
    return done


def bin_closed(ws: Workspace, jd_id: int) -> Sweep:
    """Right after a status change: bin this job's saved ad if it closed unsuccessfully."""
    if ws.trash_dir is None:
        return Sweep()
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
        application = store.get_application(conn, jd_id)
    if jd is None or not jd.source_file or application is None:
        return Sweep()
    if application.status not in UNSUCCESSFUL:
        return Sweep()
    path = ws.jd_dir / jd.source_file
    if not path.is_file():
        return Sweep()
    try:
        move_to_trash(path, ws.trash_dir)
    except TrashError as exc:
        return Sweep(failed=[(path.name, str(exc))])
    return Sweep(binned=[Binned(path.name, jd_id, f"closed: {application.status.value}")])


def _reason(rows, cutoff: datetime) -> tuple[int, str] | None:
    for jd_id, _, status in rows:
        if status in UNSUCCESSFUL:
            return jd_id, f"closed: {status.value}"
    for jd_id, added, _ in rows:
        if added < cutoff:
            return jd_id, f"added {added:%Y-%m-%d}, over {KEEP_DAYS} days ago"
    return None


def _when(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
