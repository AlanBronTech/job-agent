"""Recording where an application stands: applied, and what became of it.

Moved from `cli/apply.py` so the batch "mark not applied" in the UI writes the
same record the CLI does, with no logic of its own (spec 002, T007; the
`outcome` half of 001's T039).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from jobagent.core import store
from jobagent.core.models import Application, ApplicationStatus, JobDescription, Worth
from jobagent.services.refusals import NoSuchAd
from jobagent.services.workspace import Workspace


def save(
    ws: Workspace,
    jd_id: int,
    *,
    status: ApplicationStatus,
    applied_on: date | None = None,
    channel: str | None = None,
    reposted_on: date | None = None,
    worth: Worth | None = None,
    worth_why: str = "",
    notes: str = "",
) -> tuple[JobDescription, Application]:
    """Create or update the ad's application row. Notes are appended, never replaced.

    Raises NoSuchAd, and StoreError if the write fails.
    """
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
        if jd is None:
            raise NoSuchAd(jd_id)
        now = datetime.now(timezone.utc)
        application = store.get_application(conn, jd_id) or Application(
            jd_id=jd_id, updated_at=now
        )
        application.status = status
        application.updated_at = now
        if applied_on is not None:
            application.applied_on = applied_on
        if channel is not None:
            application.channel = channel
        if reposted_on is not None:
            application.reposted_on = reposted_on
        if worth is not None:
            application.worth_applying = worth
            # Stated by Alan, so it is no longer an inference from notes.
            application.worth_derived = False
        if worth_why:
            application.worth_why = worth_why
        if notes:
            application.notes = (
                f"{application.notes}\n{notes}".strip() if application.notes else notes
            )
        store.save_application(conn, application)
    return jd, application


def outcome(
    ws: Workspace,
    jd_id: int,
    status: ApplicationStatus,
    *,
    worth: Worth | None = None,
    why: str = "",
    note: str = "",
) -> tuple[JobDescription, Application]:
    """Record what became of an application, or that it was never made."""
    return save(ws, jd_id, status=status, worth=worth, worth_why=why, notes=note)
