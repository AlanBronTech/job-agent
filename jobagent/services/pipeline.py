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


# What the UI's dropdowns offer. Plain words for each status, in the order an
# application moves through them.
STATUS_LABELS: dict[str, str] = {
    "identified": "Saved, not applied yet",
    "applied": "Applied",
    "applied_no_reply": "Applied, no reply",
    "recruiter_call": "Recruiter call",
    "interview_1": "First interview",
    "interview_2": "Second interview",
    "offer": "Offer",
    "rejected_screen": "Rejected at screening",
    "rejected_after_interview": "Rejected after interview",
    "ghosted_after_contact": "Went quiet after contact",
    "withdrew": "Withdrew",
    "not_applied": "Not applied",
}

CHANNELS: tuple[str, ...] = (
    "seek",
    "linkedin",
    "careers site",
    "recruiter",
    "email",
    "referral",
    "other",
)

WORTH_LABELS: dict[str, str] = {
    "yes": "Yes, worth the day",
    "no": "No, not worth it",
    "unsure": "Unsure",
}


def update_from_form(
    ws: Workspace,
    jd_id: int,
    *,
    status: str,
    applied_on: str = "",
    channel: str = "",
    channel_detail: str = "",
    worth: str = "",
    why: str = "",
    note: str = "",
    today: date,
) -> tuple[JobDescription, Application]:
    """The UI's pipeline form, validated, as one `save`.

    An application recorded as applied with no date gets today's, the way
    `jobagent apply` does. A channel is "recruiter — Jane Smith" when a detail
    is given, the convention the CLI's records already use.
    """
    try:
        new_status = ApplicationStatus(status)
    except ValueError as exc:
        raise ValueError(f"Unknown status {status!r}") from exc
    day: date | None = None
    if applied_on:
        day = date.fromisoformat(applied_on)
    chosen = channel if channel in CHANNELS else ""
    detail = channel_detail.strip()
    full_channel = None
    if chosen and detail:
        full_channel = f"{chosen} — {detail}"
    elif chosen:
        full_channel = chosen
    elif detail:
        full_channel = detail
    with store.open_store(ws.db_path) as conn:
        existing = store.get_application(conn, jd_id)
    if day is None and new_status is ApplicationStatus.applied and not (existing and existing.applied_on):
        day = today
    return save(
        ws,
        jd_id,
        status=new_status,
        applied_on=day,
        channel=full_channel,
        worth=Worth(worth) if worth in WORTH_LABELS else None,
        worth_why=why.strip(),
        notes=note.strip(),
    )
