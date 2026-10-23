"""Contacts: the recruiters and people worth a regular follow-up (REVIEW-2026-10-18, task 5).

A CRM for one person, nothing more. The 15-30 agency recruiters and contract
desks matter more than 600 LinkedIn connections, and their value comes from
re-touching every six to eight weeks — which nobody does without a reminder.
`touch` records a contact made and sets the next one; `due` is what
`jobagent status` shows.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from jobagent.core import store
from jobagent.core.models import Contact, ContactKind
from jobagent.services.refusals import BadDate, NoSuchAd, Refusal
from jobagent.services.workspace import Workspace

# The re-touch cadence when none is given: inside the six-to-eight weeks that
# keeps a recruiter's shortlist warm.
DEFAULT_CADENCE = timedelta(weeks=6)
# "Due this week": anything overdue, or falling due in the next seven days.
DUE_WINDOW = timedelta(days=7)

_INTERVAL = re.compile(r"^\s*(\d+)\s*([dwm])\s*$", re.IGNORECASE)


class NoSuchContact(Refusal):
    def __init__(self, contact_id: int) -> None:
        super().__init__(f"no contact with id {contact_id}")
        self.contact_id = contact_id


def next_date(spec: str | None, start: date) -> date:
    """`6w`, `10d`, `2m` (30-day months) after `start`, or a YYYY-MM-DD date.

    None means the default cadence. A date before `start` is refused: a
    follow-up is something still to do.
    """
    if spec is None:
        return start + DEFAULT_CADENCE
    match = _INTERVAL.match(spec)
    if match:
        n, unit = int(match[1]), match[2].lower()
        return start + timedelta(days=n * {"d": 1, "w": 7, "m": 30}[unit])
    try:
        when = date.fromisoformat(spec.strip())
    except ValueError:
        raise BadDate(f"{spec!r} is neither an interval (6w, 10d, 2m) nor a YYYY-MM-DD date.")
    if when < start:
        raise BadDate(f"{when:%Y-%m-%d} is before {start:%Y-%m-%d}: a follow-up is still to come.")
    return when


def add(
    ws: Workspace,
    *,
    name: str,
    firm: str = "",
    kind: ContactKind = ContactKind.agency_recruiter,
    specialty: str = "",
    channel: str = "",
    first_contact: date | None = None,
    next_followup: str | None = None,
    notes: str = "",
    jd_id: int | None = None,
    today: date | None = None,
) -> Contact:
    today = today or date.today()
    first = first_contact or today
    if first > today:
        raise BadDate(f"{first:%Y-%m-%d} is in the future; first contact is something that happened.")
    if not name.strip():
        raise BadDate("A contact needs a name.")
    contact = Contact(
        name=name.strip(), firm=firm.strip(), kind=kind, specialty=specialty.strip(),
        channel=channel.strip(), first_contact=first, last_touch=first,
        next_followup=next_date(next_followup, first),
        notes=notes.strip(), jd_id=jd_id, created_at=datetime.now(timezone.utc),
    )
    with store.open_store(ws.db_path) as conn:
        if jd_id is not None and store.get_jd(conn, jd_id) is None:
            raise NoSuchAd(jd_id)
        contact.id = store.add_contact(conn, contact)
    return contact


def list_all(ws: Workspace) -> list[Contact]:
    with store.open_store(ws.db_path) as conn:
        return store.list_contacts(conn)


def touch(
    ws: Workspace,
    contact_id: int,
    *,
    next_followup: str | None = None,
    note: str = "",
    today: date | None = None,
) -> Contact:
    """Record a contact made today and set the next one. A note is appended, dated."""
    today = today or date.today()
    with store.open_store(ws.db_path) as conn:
        contact = _get(conn, contact_id)
        contact.last_touch = today
        contact.next_followup = next_date(next_followup, today)
        if note.strip():
            line = f"{today:%Y-%m-%d}: {note.strip()}"
            contact.notes = f"{contact.notes}\n{line}" if contact.notes else line
        store.update_contact(conn, contact)
    return contact


def link(ws: Workspace, contact_id: int, jd_id: int) -> Contact:
    with store.open_store(ws.db_path) as conn:
        contact = _get(conn, contact_id)
        if store.get_jd(conn, jd_id) is None:
            raise NoSuchAd(jd_id)
        contact.jd_id = jd_id
        store.update_contact(conn, contact)
    return contact


def due(ws: Workspace, today: date | None = None) -> list[Contact]:
    """Overdue, or due within the week; soonest first."""
    horizon = (today or date.today()) + DUE_WINDOW
    return [
        c for c in list_all(ws)
        if c.next_followup is not None and c.next_followup <= horizon
    ]


def _get(conn, contact_id: int) -> Contact:
    contact = store.get_contact(conn, contact_id)
    if contact is None:
        raise NoSuchContact(contact_id)
    return contact
