"""Applications made outside the tool: record them, list them, link them to an ad.

An application made before the tool existed, or straight through an employer's
portal, used to be invisible: no ad, no output folder, so nothing could say
"you applied for this in May". Recording one makes it count for company
history and for the six-month rule exactly as a tracked application does
(spec 002, FR-012..014).

Linking happens when the ad for that application is added later. The ad's own
application row then becomes the record, carrying the original date, status
and notes, and the outside row is marked linked so it is not counted twice.
The ad's text was captured after the decision to apply, which the eval
builder detects from the dates.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from jobagent.core import store
from jobagent.core.models import Application, ApplicationStatus, OutsideApplication
from jobagent.services.refusals import BadDate, NoSuchAd
from jobagent.services.workspace import Workspace


class NoSuchOutside(NoSuchAd):
    """No outside application with that id."""

    def __init__(self, outside_id: int) -> None:
        Exception.__init__(self, f"no outside application with id {outside_id}")
        self.jd_id = outside_id
        self.outside_id = outside_id


def record_outside(
    ws: Workspace,
    *,
    company: str,
    title: str,
    applied_on: date,
    requisition_id: str | None = None,
    channel: str | None = None,
    status: ApplicationStatus = ApplicationStatus.applied,
    notes: str = "",
    today: date | None = None,
) -> OutsideApplication:
    if applied_on > (today or date.today()):
        raise BadDate(
            f"{applied_on:%Y-%m-%d} is in the future. An application date is a "
            "record of something that has happened."
        )
    if not company.strip() or not title.strip():
        raise BadDate("Company and role title are both needed.")
    record = OutsideApplication(
        company=company.strip(),
        title=title.strip(),
        requisition_id=(requisition_id or "").strip() or None,
        applied_on=applied_on,
        channel=channel,
        status=status,
        notes=notes,
        created_at=datetime.now(timezone.utc),
    )
    with store.open_store(ws.db_path) as conn:
        record.id = store.add_outside(conn, record)
    return record


def list_outside(ws: Workspace) -> list[OutsideApplication]:
    with store.open_store(ws.db_path) as conn:
        return store.list_outside(conn)


def link_outside(ws: Workspace, outside_id: int, jd_id: int) -> Application:
    """Make the ad's application the record of an outside one. Returns that row."""
    with store.open_store(ws.db_path) as conn:
        record = store.get_outside(conn, outside_id)
        if record is None:
            raise NoSuchOutside(outside_id)
        if store.get_jd(conn, jd_id) is None:
            raise NoSuchAd(jd_id)
        application = store.get_application(conn, jd_id) or Application(
            jd_id=jd_id, updated_at=datetime.now(timezone.utc)
        )
        application.status = record.status
        application.applied_on = record.applied_on
        if record.channel and not application.channel:
            application.channel = record.channel
        note = f"Linked from outside application {outside_id}" + (
            f": {record.notes}" if record.notes else "."
        )
        application.notes = f"{application.notes}\n{note}".strip() if application.notes else note
        application.updated_at = datetime.now(timezone.utc)
        store.save_application(conn, application)
        if record.requisition_id and not store.get_jd(conn, jd_id).requisition_id:
            store.set_jd_identifiers(conn, jd_id, requisition_id=record.requisition_id)
        store.link_outside(conn, outside_id, jd_id)
    return application
