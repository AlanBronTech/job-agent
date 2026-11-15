"""The master resume chosen for an ad, for every place the assessment is shown.

Free: reads the registry and applies `core.masters.select_master`. A broken
registry never stops a score or a page from showing; it comes back as a
choice whose reason says what is wrong, so it is seen where the choice would
have been.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from jobagent.core import store
from jobagent.core.masters import load_masters, select_master
from jobagent.core.models import (
    JobDescription,
    MasterChoice,
    MasterResume,
    RoleClassification,
)
from jobagent.core.profile import ProfileError
from jobagent.services.refusals import NoSuchAd, UnknownMaster
from jobagent.services.workspace import Workspace


def registry(ws: Workspace) -> list[MasterResume]:
    """Every master, or none when there is no profile or the list is invalid."""
    if ws.profile_dir is None:
        return []
    try:
        return load_masters(ws.profile_dir)
    except ProfileError:
        return []


def choose(
    ws: Workspace, jd: JobDescription, kind: RoleClassification | None
) -> MasterChoice | None:
    """The choice for this ad, or None when there is no profile or no registry."""
    if ws.profile_dir is None:
        return None
    try:
        registry = load_masters(ws.profile_dir)
    except ProfileError as exc:
        return MasterChoice(
            reason=f"No master chosen: the master list is invalid. {exc}"
        )
    return select_master(jd, kind, registry)


# --------------------------------------------------------------------------- #
# Which resume went, resolved when the application is recorded
# --------------------------------------------------------------------------- #


CUSTOM = "custom"
NOT_A_TARGET = "not_a_target"


@dataclass
class SentResume:
    """What to record about the resume that went with an application."""

    # A master's id, "custom", or None when nothing can be said.
    master: str | None
    # What JobAgent suggested: a master's id, "not_a_target", or None.
    suggested: str | None
    # A master's file to record as sent, when no file was named; else None.
    file: Path | None = None
    # True when nothing was named and the suggestion was taken as what went.
    assumed: bool = False

    @property
    def overrode(self) -> bool:
        return (self.master not in (None, CUSTOM) and self.suggested is not None
                and self.master != self.suggested)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_sent(
    ws: Workspace,
    jd_id: int,
    *,
    chosen: str | None = None,
    sent_resume: Path | None = None,
    sent_as_generated: bool = False,
) -> SentResume:
    """Which resume went with this application. Free; writes nothing.

    `chosen` is what Alan named: a master's id or "custom". Without it, a
    file identical to a master is that master, any other file or the
    generated copies are custom, and with nothing named at all the suggested
    master is assumed, with its file to record as sent. Raises UnknownMaster
    for a name the registry does not list, before anything is written.
    """
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
        kind = store.get_role_kind(conn, jd_id) if jd is not None else None
        existing = store.get_application(conn, jd_id) if jd is not None else None
    if jd is None:
        raise NoSuchAd(jd_id)
    named = chosen is not None or sent_resume is not None or sent_as_generated
    if not named and existing is not None and existing.resume_master is not None:
        # Already recorded; applying again with nothing named changes nothing.
        return SentResume(master=None, suggested=None)
    registry = load_masters(ws.profile_dir) if ws.profile_dir is not None else []
    choice = select_master(jd, kind, registry)
    suggested = (choice.master.id if choice and choice.master
                 else NOT_A_TARGET if choice and choice.not_a_target else None)

    def file_of(master) -> Path:
        return master.pdf or master.docx

    if chosen == CUSTOM:
        return SentResume(master=CUSTOM, suggested=suggested)
    if chosen is not None:
        master = next((m for m in registry if m.id == chosen), None)
        if master is None:
            raise UnknownMaster(chosen, [m.id for m in registry])
        return SentResume(master=master.id, suggested=suggested,
                          file=None if sent_resume else file_of(master))
    if sent_as_generated:
        return SentResume(master=CUSTOM, suggested=suggested)
    if sent_resume is not None:
        # A missing or unreadable file is refused by the sent check that
        # follows; here it can only be custom.
        sent_path = Path(sent_resume)
        digest = _sha256(sent_path) if registry and sent_path.is_file() else None
        for master in registry if digest else []:
            for path in (master.pdf, master.docx):
                if path is not None and _sha256(path) == digest:
                    return SentResume(master=master.id, suggested=suggested)
        return SentResume(master=CUSTOM, suggested=suggested)
    if choice is not None and choice.master is not None:
        return SentResume(master=choice.master.id, suggested=suggested,
                          file=file_of(choice.master), assumed=True)
    return SentResume(master=None, suggested=suggested)
