"""Revise a generated document by telling the tool what is wrong, in words.

REVIEW-2026-10-18 task 2. A correction made in Word or Claude.ai is lost the
moment it is made; one given here is stored, can be counted, and once it
recurs can be promoted into `voice.md`, a `note_for_writer` or the profile.
The goal it serves is that what is sent is what was generated.

A revision is a generate run for one document with two things added: the
previous draft, read back from the copy `generate` kept, and Alan's note. The
validators and the claim check run again exactly as on a first draft, so a
note asking for something the evidence does not hold is still refused
(prompts/revision.md says so to the model; the checks enforce it).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from jobagent.adapters.docx_reader import DocxReadError, read_sections
from jobagent.core import store
from jobagent.core.models import DocumentKind, JobDescription, RevisionNote
from jobagent.services import documents, sent
from jobagent.services.refusals import EditedByHand, NoGeneratedCopy, NoSuchAd
from jobagent.services.results import GenerateResult
from jobagent.services.workspace import Workspace


@dataclass
class RevisionPlan:
    jd: JobDescription
    kind: DocumentKind
    folder: str
    kept: str  # the newest kept copy: the previous draft
    visible: str | None  # the file Alan reads, None if it has been moved or deleted
    edited: bool  # the visible file differs from the kept copy
    previous: str  # the previous draft as text


def plan(ws: Workspace, jd_id: int, kind: DocumentKind, today: date) -> RevisionPlan:
    """What a revision would start from. Spends nothing; refuses if there is nothing."""
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
    if jd is None:
        raise NoSuchAd(jd_id)
    current = ws.documents.list_for(jd, today).current
    label = "resume" if kind is DocumentKind.resume else "cover letter"
    if current is None:
        raise NoGeneratedCopy(label, ws.documents.folder_name(jd, today))
    kept = sent.latest_generated(ws, jd, current.name, kind, today)
    if kept is None:
        raise NoGeneratedCopy(label, current.name)
    kept_path = ws.documents.local_path(jd, current.name, kept, today)
    name = Path(kept).name
    visible = name if name in {f.name for f in current.files} else None
    edited = visible is not None and _sha(
        ws.documents.local_path(jd, current.name, visible, today)
    ) != _sha(kept_path)
    try:
        sections = read_sections(kept_path, kind.value)
    except DocxReadError as exc:
        raise NoGeneratedCopy(label, f"{current.name} ({exc})") from exc
    previous = "\n\n".join(
        (f"{s.name}\n" if kind is DocumentKind.resume else "") + "\n".join(s.paragraphs)
        for s in sections
    )
    return RevisionPlan(jd, kind, current.name, kept, visible, edited, previous)


def revisable(ws: Workspace, jd_id: int, today: date) -> list[RevisionPlan]:
    """The documents a revision could start from now, for the ad's page."""
    plans = []
    for kind in DocumentKind:
        try:
            plans.append(plan(ws, jd_id, kind, today))
        except NoGeneratedCopy:
            continue
    return plans


def revise(
    ws: Workspace,
    config,
    ctx,
    jd_id: int,
    *,
    kind: DocumentKind,
    note: str,
    today: date,
    now: datetime,
    replace_edits: bool = False,
    before_spend=None,
    check_claims: bool | None = None,
) -> tuple[GenerateResult, RevisionNote]:
    """Write the document again with Alan's note. The previous version stays kept.

    Refuses, before anything is written or spent, when the visible file has
    been edited by hand since it was generated, unless `replace_edits`: then
    the edited file is kept under `.edited/` first, so nothing is lost.
    """
    if not note.strip():
        raise ValueError("A revision needs a note saying what to change.")
    revision = plan(ws, jd_id, kind, today)
    if revision.edited and not replace_edits:
        raise EditedByHand(revision.visible)
    if revision.edited:
        ws.documents.keep_edited(revision.jd, revision.folder, revision.visible, now, today)

    # Recorded before spending: the note is Alan's judgement of the draft
    # whether or not this run succeeds.
    record = RevisionNote(jd_id=jd_id, kind=kind, note=note.strip(), created_at=now)
    with store.open_store(ws.db_path) as conn:
        record.id = store.add_revision_note(conn, record)

    result = documents.generate(
        ws, config, ctx, jd_id,
        resume=kind is DocumentKind.resume,
        cover=kind is DocumentKind.cover_letter,
        questions=[],
        # Revising documents that already exist is not a new decision to
        # apply; any overrule was recorded when they were first generated.
        overrule=True,
        overwrite=True,
        today=today,
        now=now,
        before_spend=before_spend,
        check_claims=check_claims,
        review=False,
        revisions={kind.value: (revision.previous, note.strip())},
    )

    written = next(p for p in result.written if p.suffix == ".docx")
    # A NOT-READY draft revised clean (or the other way round) has a new name;
    # the old one is in the kept copy and would only mislead.
    if revision.visible and revision.visible != written.name:
        ws.documents.remove(revision.jd, revision.folder, revision.visible, today)
    record.result = next(
        (name for name in ws.documents.generated_copies(revision.jd, revision.folder, today)
         if Path(name).name == written.name),
        None,
    )
    if record.result:
        with store.open_store(ws.db_path) as conn:
            store.set_revision_result(conn, record.id, record.result)
    return result, record


def notes(ws: Workspace, jd_id: int | None = None) -> list[RevisionNote]:
    with store.open_store(ws.db_path) as conn:
        return store.list_revision_notes(conn, jd_id)


def context(ws: Workspace, jd_id: int) -> str | None:
    with store.open_store(ws.db_path) as conn:
        if store.get_jd(conn, jd_id) is None:
            raise NoSuchAd(jd_id)
        return store.get_context(conn, jd_id)


def add_context(ws: Workspace, jd_id: int, text: str, now: datetime) -> str:
    """Append a line to the ad's context. Returns the whole context."""
    current = context(ws, jd_id)
    line = text.strip()
    combined = f"{current}\n{line}" if current and line else (line or current or "")
    with store.open_store(ws.db_path) as conn:
        store.set_context(conn, jd_id, combined, now)
    return combined


def set_context(ws: Workspace, jd_id: int, text: str, now: datetime) -> None:
    """Replace the ad's context; empty clears it."""
    context(ws, jd_id)
    with store.open_store(ws.db_path) as conn:
        store.set_context(conn, jd_id, text, now)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
