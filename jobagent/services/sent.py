"""What was sent, kept beside what was generated, and how far apart they are.

REVIEW-2026-10-18 task 1. The target is that the documents sent are the
documents generated; this is the measurement. Two records make it possible:

* `generate` keeps a read-only copy of each document it writes, under
  `.generated/<run time>/` in the application folder (services/documents.py).
* `record` copies each file that went to an employer into `sent/<date>/`,
  and adds a row saying which generated copy it is to be compared with.

Neither copy is ever replaced. In the first six applications looked at, five
had the sent version saved over the generated one, and with it went the only
thing the edit could have been measured against.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from jobagent.adapters import docs
from jobagent.adapters.docx_reader import DocxReadError, read_sections
from jobagent.core import store
from jobagent.core.diff import DocumentDiff, compare
from jobagent.core.models import DocumentKind, JobDescription, SentDocument
from jobagent.services.refusals import (
    NoGeneratedCopy,
    NoSuchAd,
    NothingSent,
    SentFileUnusable,
)
from jobagent.services.workspace import Workspace

SENT_SUFFIXES = (".docx", ".pdf")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@dataclass
class Comparison:
    sent: SentDocument
    diff: DocumentDiff | None
    # Why there is no diff: no generated copy, or a file diff cannot read.
    problem: str | None = None


@dataclass
class Prepared:
    """Everything `commit` will copy and record, checked; nothing touched yet.

    Split from `commit` so the UI can run its other refusals — the pipeline
    form's — between the two: a guard that moves things runs after every
    refusal. `uploads` holds the browser's files until `commit` copies them.
    """

    jd: JobDescription
    folder: str | None
    # (kind, sent file or None for the kept copy, generated original to record, kept copy)
    plans: list[tuple[DocumentKind, Path | None, Path | None, str | None]]
    as_generated: bool
    uploads: tempfile.TemporaryDirectory | None = None


def record(ws: Workspace, jd_id: int, *, sent_on: date, today: date, now: datetime, **files) -> list[SentDocument]:
    """Record what went to the employer for one ad: `prepare`, then `commit`."""
    return commit(ws, prepare(ws, jd_id, today=today, **files), sent_on=sent_on, today=today, now=now)


def prepare(
    ws: Workspace,
    jd_id: int,
    *,
    resume: Path | None = None,
    letter: Path | None = None,
    as_generated: bool = False,
    generated_resume: Path | None = None,
    generated_letter: Path | None = None,
    today: date,
) -> Prepared:
    """Every refusal for a record, and nothing on disk touched.

    `as_generated` says the generated documents went unedited, and records
    the newest kept copy of each. Otherwise `resume` and `letter` name the
    files that were sent. `generated_resume` and `generated_letter` name the
    generated originals for a folder from before copies were kept.
    """
    if as_generated and (resume or letter):
        raise ValueError("as_generated records the generated copies; name no files with it")
    if not (as_generated or resume or letter):
        raise ValueError("nothing to record")
    jd = _jd(ws, jd_id)

    for path in (resume, letter):
        if path is not None:
            _check(path, SENT_SUFFIXES)
    for path in (generated_resume, generated_letter):
        if path is not None:
            _check(path, (".docx",))

    folder = _existing_folder(ws, jd, today)
    plans: list[tuple[DocumentKind, Path | None, Path | None, str | None]] = []
    for kind, given, original in (
        (DocumentKind.resume, resume, generated_resume),
        (DocumentKind.cover_letter, letter, generated_letter),
    ):
        latest = None if original or folder is None else latest_generated(ws, jd, folder, kind, today)
        if as_generated:
            if latest is None:
                continue
            plans.append((kind, None, None, latest))
        elif given is not None:
            plans.append((kind, given, original, latest))
    if not plans:
        raise NoGeneratedCopy("resume or cover letter", folder or ws.documents.folder_name(jd, today))
    return Prepared(jd=jd, folder=folder, plans=plans, as_generated=as_generated)


def prepare_uploads(
    ws: Workspace,
    jd_id: int,
    *,
    resume: tuple[str, bytes] | None = None,
    letter: tuple[str, bytes] | None = None,
    as_generated: bool = False,
    today: date,
) -> Prepared:
    """`prepare` for files that arrived from the browser as (file name, bytes)."""
    holder = tempfile.TemporaryDirectory(prefix="jobagent-sent-")
    paths = {}
    for key, upload in (("resume", resume), ("letter", letter)):
        if upload is None:
            continue
        filename, data = upload
        name = _bare_name(filename)
        if len(data) > MAX_UPLOAD_BYTES:
            raise SentFileUnusable(name, f"over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
        path = Path(holder.name) / key / name
        path.parent.mkdir()
        path.write_bytes(data)
        paths[key] = path
    prepared = prepare(ws, jd_id, as_generated=as_generated, today=today, **paths)
    prepared.uploads = holder
    return prepared


def commit(
    ws: Workspace, prepared: Prepared, *, sent_on: date, today: date, now: datetime
) -> list[SentDocument]:
    """Copy and record. Returns the rows, new or existing: the same file twice is one row."""
    jd = prepared.jd
    folder = prepared.folder or ws.documents.ensure_folder(jd, today)
    try:
        with store.open_store(ws.db_path) as conn:
            existing = store.list_sent(conn, jd.id)
            rows: list[SentDocument] = []
            for kind, given, original, generated in prepared.plans:
                if original is not None:
                    generated = ws.documents.record_generated(jd, folder, original, now, today)
                source = given or ws.documents.local_path(jd, folder, generated, today)
                digest = _sha256(source)
                repeat = next(
                    (r for r in existing if r.kind is kind and r.sha256 == digest), None
                )
                if repeat is not None:
                    rows.append(repeat)
                    continue
                name = ws.documents.keep_sent(jd, folder, source, sent_on, today)
                same = generated is not None and digest == _sha256(
                    ws.documents.local_path(jd, folder, generated, today)
                )
                row = SentDocument(
                    jd_id=jd.id,
                    kind=kind,
                    folder=folder,
                    name=name,
                    sha256=digest,
                    generated=generated,
                    as_generated=prepared.as_generated or same,
                    sent_on=sent_on,
                    recorded_at=now,
                )
                row.id = store.add_sent(conn, row)
                rows.append(row)
    finally:
        if prepared.uploads is not None:
            prepared.uploads.cleanup()
    return rows


def sent_on_for(ws: Workspace, jd_id: int, today: date) -> date:
    """The application's date when it has one, else today."""
    with store.open_store(ws.db_path) as conn:
        application = store.get_application(conn, jd_id)
    return application.applied_on if application and application.applied_on else today


def summary(ws: Workspace, jd_id: int, today: date) -> list[Comparison]:
    """`compare_sent` for the ad's page: nothing recorded is an empty list."""
    try:
        return compare_sent(ws, jd_id, today)
    except NothingSent:
        return []


def recorded(ws: Workspace, jd_id: int | None = None) -> list[SentDocument]:
    with store.open_store(ws.db_path) as conn:
        if jd_id is not None and store.get_jd(conn, jd_id) is None:
            raise NoSuchAd(jd_id)
        return store.list_sent(conn, jd_id)


def compare_sent(ws: Workspace, jd_id: int, today: date) -> list[Comparison]:
    """The newest sent copy of each document for one ad, against its generated copy."""
    jd = _jd(ws, jd_id)
    latest = _latest_per_kind(recorded(ws, jd_id))
    if not latest:
        raise NothingSent(jd_id)
    return [_compare_row(ws, jd, row, today) for row in latest]


def compare_all(ws: Workspace, today: date) -> list[tuple[JobDescription, Comparison]]:
    """Every ad with anything recorded as sent, newest sent copy of each document."""
    rows = recorded(ws)
    with store.open_store(ws.db_path) as conn:
        jds = {jd.id: jd for jd in store.list_jds(conn)}
    out = []
    for jd_id in dict.fromkeys(row.jd_id for row in rows):
        jd = jds[jd_id]
        for row in _latest_per_kind([r for r in rows if r.jd_id == jd_id]):
            out.append((jd, _compare_row(ws, jd, row, today)))
    return out


def compare_files(generated: Path, sent: Path, kind: DocumentKind) -> DocumentDiff:
    """Two files, no records: for a pair from before any of this existed."""
    return compare(
        read_sections(generated, kind.value), read_sections(sent, kind.value)
    )


def kind_of(path: Path) -> DocumentKind | None:
    value = docs.document_kind(Path(path).name)
    return DocumentKind(value) if value else None


# --------------------------------------------------------------------------- #


def _compare_row(ws: Workspace, jd: JobDescription, row: SentDocument, today: date) -> Comparison:
    if row.generated is None:
        return Comparison(row, None, "no generated copy was kept for it")
    try:
        generated = ws.documents.local_path(jd, row.folder, row.generated, today)
        sent = ws.documents.local_path(jd, row.folder, row.name, today)
    except FileNotFoundError as exc:
        return Comparison(row, None, f"{exc} is no longer on disk")
    try:
        return Comparison(row, compare_files(generated, sent, row.kind))
    except DocxReadError as exc:
        return Comparison(row, None, str(exc))


def _latest_per_kind(rows: list[SentDocument]) -> list[SentDocument]:
    """Rows arrive oldest first, so the last of each kind wins."""
    latest: dict[DocumentKind, SentDocument] = {}
    for row in rows:
        latest[row.kind] = row
    return [latest[k] for k in DocumentKind if k in latest]


def latest_generated(
    ws: Workspace, jd: JobDescription, folder: str, kind: DocumentKind, today: date
) -> str | None:
    for name in ws.documents.generated_copies(jd, folder, today):
        if docs.document_kind(Path(name).name) == kind.value:
            return name
    return None


def _existing_folder(ws: Workspace, jd: JobDescription, today: date) -> str | None:
    """Where the application's records belong: this month's folder, else the
    newest earlier month's, else the newest superseded one. The documents that
    were sent are in one of those."""
    folders = ws.documents.list_for(jd, today)
    for stored in [folders.current, *folders.earlier, *folders.superseded]:
        if stored is not None:
            return stored.name
    return None


def _jd(ws: Workspace, jd_id: int) -> JobDescription:
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
    if jd is None:
        raise NoSuchAd(jd_id)
    return jd


def _check(path: Path, suffixes: tuple[str, ...]) -> None:
    path = Path(path).expanduser()
    if not path.is_file():
        raise SentFileUnusable(str(path), "no such file")
    if path.suffix.lower() not in suffixes:
        raise SentFileUnusable(str(path), f"expected {' or '.join(suffixes)}")


def _bare_name(filename: str) -> str:
    """The browser's file name, as a name and nothing else."""
    name = (filename or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name or name.startswith("."):
        raise SentFileUnusable(filename or "(no name)", "not a plain file name")
    if Path(name).suffix.lower() not in SENT_SUFFIXES:
        raise SentFileUnusable(name, f"expected {' or '.join(SENT_SUFFIXES)}")
    return name


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).expanduser().read_bytes()).hexdigest()
