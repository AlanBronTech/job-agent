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
from jobagent.adapters.docx_writer import docx_text
from jobagent.core.masters import CustomAdvice, custom_advice, load_masters, select_master
from jobagent.core.models import (
    FitAssessment,
    JobDescription,
    MasterChoice,
    MasterResume,
    RoleClassification,
)
from jobagent.core.profile import ProfileError, load_profile
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


def advise_custom(
    ws: Workspace, choice: MasterChoice | None, assessment: FitAssessment | None
) -> CustomAdvice:
    """Whether a custom resume is worth generating beside the chosen master. Free."""
    profile = None
    if ws.profile_dir is not None:
        try:
            profile = load_profile(ws.profile_dir)
        except ProfileError:
            profile = None
    master = choice.master if choice is not None else None
    text = docx_text(master.docx) if master is not None else None
    return custom_advice(choice, assessment, profile, text)


def suggest(ws: Workspace, jd_id: int) -> tuple[MasterChoice | None, CustomAdvice | None]:
    """The master suggested for a stored ad, and whether a custom resume is worth it.

    Free. (None, None) for an ad that does not exist; the caller's own lookup
    reports that.
    """
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
        if jd is None:
            return None, None
        kind = store.get_role_kind(conn, jd_id)
        assessment = store.latest_assessment(conn, jd_id)
    choice = choose(ws, jd, kind)
    return choice, advise_custom(ws, choice, assessment) if assessment else None


def file_to_send(master: MasterResume) -> Path:
    """The master's file to send: the PDF when there is one."""
    return master.pdf or master.docx


def master_on_page(path: Path) -> dict[str, str]:
    """What a master's page already says, for the longer PROFILE not to repeat (spec 005).

    Its CAREER HIGHLIGHTS and EXPERIENCE bullets, keyed "master highlight 1",
    "master bullet 1", …. Empty when the file cannot be read: the check is
    then weaker, never a reason to stop.
    """
    from jobagent.adapters.docx_reader import DocxReadError, read_sections

    try:
        sections = read_sections(path, "resume")
    except DocxReadError:
        return {}
    out: dict[str, str] = {}
    highlights = bullets = 0
    for section in sections:
        for text in section.paragraphs:
            if section.name == "CAREER HIGHLIGHTS":
                highlights += 1
                out[f"master highlight {highlights}"] = text
            elif section.name.startswith("EXPERIENCE"):
                bullets += 1
                out[f"master bullet {bullets}"] = text
    return out


def find(ws: Workspace, master_id: str) -> MasterResume:
    """The registry's master with this id; UnknownMaster otherwise."""
    listed = registry(ws)
    found = next((m for m in listed if m.id == master_id), None)
    if found is None:
        raise UnknownMaster(master_id, [m.id for m in listed])
    return found


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
    # Whether it had the longer, agency PROFILE (spec 005); None when unknown.
    long_profile: bool | None = None

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
    long_profile: bool = False,
    today=None,
) -> SentResume:
    """Which resume went with this application. Free; writes nothing.

    `chosen` is what Alan named: a master's id or "custom". Without it, a
    file identical to a master is that master, any other file or the
    generated copies are custom, and with nothing named at all the suggested
    master is assumed, with its file to record as sent. Raises UnknownMaster
    for a name the registry does not list, before anything is written.

    Spec 005: `long_profile` goes with `chosen` (the resume named had the
    longer PROFILE). The generated copies, or a file that is not a master
    (an edit of them), take the base and flag of the job's latest generated
    resume when its record has them.
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

    def generated() -> SentResume:
        from datetime import date

        from jobagent.services.documents import latest_resume_kind

        kind_of = latest_resume_kind(ws, jd, today or date.today())
        if kind_of is None:
            return SentResume(master=CUSTOM, suggested=suggested)
        return SentResume(master=kind_of[0], suggested=suggested, long_profile=kind_of[1])

    if chosen == CUSTOM:
        return SentResume(master=CUSTOM, suggested=suggested, long_profile=long_profile)
    if chosen is not None:
        master = next((m for m in registry if m.id == chosen), None)
        if master is None:
            raise UnknownMaster(chosen, [m.id for m in registry])
        # A copy with a longer profile is not the master's own file.
        keep = None if sent_resume or long_profile else file_of(master)
        return SentResume(master=master.id, suggested=suggested, file=keep,
                          long_profile=long_profile)
    if sent_as_generated:
        return generated()
    if sent_resume is not None:
        # A missing or unreadable file is refused by the sent check that
        # follows; here it can only be custom.
        sent_path = Path(sent_resume)
        digest = _sha256(sent_path) if registry and sent_path.is_file() else None
        for master in registry if digest else []:
            for path in (master.pdf, master.docx):
                if path is not None and _sha256(path) == digest:
                    return SentResume(master=master.id, suggested=suggested, long_profile=False)
        return generated()
    if choice is not None and choice.master is not None:
        return SentResume(master=choice.master.id, suggested=suggested,
                          file=file_of(choice.master), assumed=True, long_profile=False)
    return SentResume(master=None, suggested=suggested)
