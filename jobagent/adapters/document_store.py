"""Where generated documents live, behind one interface.

Today there is one place: a folder per application under OUTPUT_DIR, opened in
Word on the same Mac. A hosted version would keep them in object storage and
hand them over as downloads. The workflows in `services/` only ever talk to a
`DocumentStore`, and refer to a document by (folder name, file name), never by
a filesystem path, so that version changes this module and nothing that calls
it (specs/001-local-ui, FR-022).

`docx_writer` still writes to a path. `path_for_write` hands it one; a hosted
store would hand it a temporary file and upload it afterwards. That is
deliberate, and not a reason to change the writer.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from jobagent.adapters import desktop, docs
from jobagent.core.models import JobDescription


@dataclass(frozen=True)
class StoredFile:
    name: str
    modified: datetime


@dataclass(frozen=True)
class StoredFolder:
    name: str
    month: str  # "2026-09", from the folder name
    superseded: bool
    files: tuple[StoredFile, ...]

    @property
    def has_documents(self) -> bool:
        return any(f.name.endswith(".docx") for f in self.files)

    @property
    def modified(self) -> datetime | None:
        return max((f.modified for f in self.files), default=None)


@dataclass
class OutputFolders:
    """Everything on disk for one ad.

    `current` is this month's live folder, the one a generate run writes to.
    `superseded` holds folders moved aside, newest first; one of them may hold
    the documents that were actually sent. `earlier` holds live folders from
    earlier months.
    """

    current: StoredFolder | None = None
    superseded: list[StoredFolder] = field(default_factory=list)
    earlier: list[StoredFolder] = field(default_factory=list)

    @property
    def all(self) -> list[StoredFolder]:
        return ([self.current] if self.current else []) + self.superseded + self.earlier

    @property
    def any(self) -> bool:
        """The "has this been done" answer: a .docx anywhere for this ad.

        Counts superseded and earlier folders too. The store is not the record
        of what has been done; documents on disk are.
        """
        return any(folder.has_documents for folder in self.all)


class DocumentStore(Protocol):
    def folder_name(self, jd: JobDescription, when: date) -> str: ...

    def path_for_write(self, jd: JobDescription, when: date, name: str) -> Path: ...

    def write_text(self, jd: JobDescription, when: date, name: str, text: str) -> Path: ...

    def supersede(self, jd: JobDescription, when: date, now: datetime) -> str | None: ...

    def list_for(self, jd: JobDescription, today: date) -> OutputFolders: ...

    def index(self, jds: Iterable[JobDescription], today: date) -> dict[int, OutputFolders]: ...

    def keep_generated(self, jd: JobDescription, when: date, name: str, now: datetime) -> str: ...

    def record_generated(
        self, jd: JobDescription, folder: str, source: Path, now: datetime, today: date
    ) -> str: ...

    def generated_copies(self, jd: JobDescription, folder: str, today: date) -> list[str]: ...

    def keep_sent(
        self, jd: JobDescription, folder: str, source: Path, sent_on: date, today: date
    ) -> str: ...

    def ensure_folder(self, jd: JobDescription, when: date) -> str: ...

    def keep_record(self, jd: JobDescription, when: date, now: datetime, document: str, data: dict) -> None: ...

    def latest_record(self, jd: JobDescription, when: date, document: str) -> dict | None: ...

    def keep_edited(self, jd: JobDescription, folder: str, name: str, now: datetime, today: date) -> str: ...

    def remove(self, jd: JobDescription, folder: str, name: str, today: date) -> None: ...

    def local_path(self, jd: JobDescription, folder: str, name: str, today: date) -> Path: ...

    def open(self, jd: JobDescription, folder: str, name: str, today: date) -> None: ...

    def reveal(self, jd: JobDescription, folder: str, today: date) -> None: ...


class LocalFolderStore:
    """Application folders under one directory on this machine."""

    def __init__(self, output_dir: Path, *, run: desktop.Runner | None = None) -> None:
        self.output_dir = Path(output_dir).expanduser()
        self._run = run

    # -- writing ------------------------------------------------------------

    def folder_name(self, jd: JobDescription, when: date) -> str:
        return docs.application_folder_path(self.output_dir, jd, when=when).name

    def path_for_write(self, jd: JobDescription, when: date, name: str) -> Path:
        return docs.application_folder(self.output_dir, jd, when=when) / name

    def write_text(self, jd: JobDescription, when: date, name: str, text: str) -> Path:
        folder = docs.application_folder(self.output_dir, jd, when=when)
        return docs.write_text(folder, name, text)

    def supersede(self, jd: JobDescription, when: date, now: datetime) -> str | None:
        """Move this month's folder aside. None if there is nothing to move."""
        folder = docs.application_folder_path(self.output_dir, jd, when=when)
        if not folder.is_dir():
            return None
        return docs.supersede_folder(folder, now).name

    # -- kept copies --------------------------------------------------------
    #
    # Names below are relative to the application folder, as in
    # `.generated/20261021T101500/AlanBron_Resume_X.docx`. The visible file is
    # the one Alan edits; these are the records the edits are measured against.

    def keep_generated(self, jd: JobDescription, when: date, name: str, now: datetime) -> str:
        """Keep a read-only copy of a file this run just wrote, under its run time."""
        folder = docs.application_folder_path(self.output_dir, jd, when=when)
        relative = f"{docs.GENERATED_DIR}/{now:%Y%m%dT%H%M%S}/{name}"
        docs.keep_copy(folder / name, folder / relative)
        return relative

    def record_generated(
        self, jd: JobDescription, folder: str, source: Path, now: datetime, today: date
    ) -> str:
        """Keep a generated file from before copies were kept, named as recorded."""
        stored = self._find(jd, folder, today)
        relative = f"{docs.GENERATED_DIR}/recorded-{now:%Y%m%dT%H%M%S}/{Path(source).name}"
        docs.keep_copy(Path(source).expanduser(), self.output_dir / stored.name / relative)
        return relative

    def generated_copies(self, jd: JobDescription, folder: str, today: date) -> list[str]:
        """Every kept generated copy in a folder, newest run first."""
        root = self.output_dir / self._find(jd, folder, today).name / docs.GENERATED_DIR
        if not root.is_dir():
            return []
        runs = sorted((p for p in root.iterdir() if p.is_dir()), key=_run_order, reverse=True)
        return [
            f"{docs.GENERATED_DIR}/{run.name}/{path.name}"
            for run in runs
            for path in sorted(run.iterdir())
            if path.is_file() and path.suffix == ".docx" and not path.name.startswith((".", "~$"))
        ]

    def keep_sent(
        self, jd: JobDescription, folder: str, source: Path, sent_on: date, today: date
    ) -> str:
        stored = self._find(jd, folder, today)
        relative = f"{docs.SENT_DIR}/{sent_on:%Y-%m-%d}/{Path(source).name}"
        docs.keep_copy(Path(source).expanduser(), self.output_dir / stored.name / relative)
        return relative

    def ensure_folder(self, jd: JobDescription, when: date) -> str:
        """This month's folder, created if absent. Returns its name."""
        return docs.application_folder(self.output_dir, jd, when=when).name

    def keep_record(self, jd: JobDescription, when: date, now: datetime, document: str, data: dict) -> None:
        """What a run found in one document, kept beside that run's copies.

        `assessment.md` is rewritten by every run, and a revise writes only one
        document: without this, the other document's blockers vanished from it.
        """
        folder = docs.application_folder(self.output_dir, jd, when=when)
        path = folder / docs.GENERATED_DIR / f"{now:%Y%m%dT%H%M%S}" / f"record-{document}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            raise docs.DocsError(f"Could not write {path}: {exc}") from exc

    def latest_record(self, jd: JobDescription, when: date, document: str) -> dict | None:
        """The newest kept record for one document in this month's folder."""
        root = docs.application_folder_path(self.output_dir, jd, when=when) / docs.GENERATED_DIR
        if not root.is_dir():
            return None
        for run in sorted((p for p in root.iterdir() if p.is_dir()), key=_run_order, reverse=True):
            path = run / f"record-{document}.json"
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return None
        return None

    def keep_edited(self, jd: JobDescription, folder: str, name: str, now: datetime, today: date) -> str:
        """Keep a hand-edited document before a revision writes over it.

        Under `.edited/`, not `.generated/`: it is not what the tool wrote, and
        `diff` must never compare against it as though it were.
        """
        source = self.local_path(jd, folder, name, today)
        relative = f"{docs.EDITED_DIR}/{now:%Y%m%dT%H%M%S}/{name}"
        docs.keep_copy(source, source.parent / relative)
        return relative

    def remove(self, jd: JobDescription, folder: str, name: str, today: date) -> None:
        """Delete one visible file. Only ever one that a kept copy already holds."""
        self.local_path(jd, folder, name, today).unlink()

    def local_path(self, jd: JobDescription, folder: str, name: str, today: date) -> Path:
        """A file in one of this ad's folders, for reading. Nothing outside them."""
        root = (self.output_dir / self._find(jd, folder, today).name).resolve()
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError(name)
        return path

    # -- reading ------------------------------------------------------------

    def list_for(self, jd: JobDescription, today: date) -> OutputFolders:
        return self._group(jd, today, self._listing())

    def index(self, jds: Iterable[JobDescription], today: date) -> dict[int, OutputFolders]:
        """Folders for many ads from one directory listing, for the list page."""
        listing = self._listing()
        return {jd.id: self._group(jd, today, listing) for jd in jds if jd.id is not None}

    # -- opening ------------------------------------------------------------

    def open(self, jd: JobDescription, folder: str, name: str, today: date) -> None:
        stored = self._find(jd, folder, today)
        if name not in {f.name for f in stored.files}:
            raise FileNotFoundError(name)
        desktop.open_file(self.output_dir / stored.name / name, root=self.output_dir, **self._kw())

    def reveal(self, jd: JobDescription, folder: str, today: date) -> None:
        stored = self._find(jd, folder, today)
        desktop.reveal(self.output_dir / stored.name, root=self.output_dir, **self._kw())

    # -- internals ----------------------------------------------------------

    def _kw(self) -> dict:
        return {} if self._run is None else {"run": self._run}

    def _find(self, jd: JobDescription, folder: str, today: date) -> StoredFolder:
        """Only a folder this store listed for this ad can be opened."""
        for stored in self.list_for(jd, today).all:
            if stored.name == folder:
                return stored
        raise FileNotFoundError(folder)

    def _listing(self) -> dict[str, list[Path]]:
        """Every application folder, keyed by the text after the first `_`."""
        by_suffix: dict[str, list[Path]] = {}
        if not self.output_dir.is_dir():
            return by_suffix
        for path in self.output_dir.iterdir():
            _, sep, suffix = path.name.partition("_")
            if sep and suffix and path.is_dir():
                by_suffix.setdefault(suffix, []).append(path)
        return by_suffix

    def _group(
        self, jd: JobDescription, today: date, listing: dict[str, list[Path]]
    ) -> OutputFolders:
        this_month = docs.application_folder_path(self.output_dir, jd, when=today).name
        _, _, suffix = this_month.partition("_")
        result = OutputFolders()
        for path in listing.get(suffix, []):
            stored = _stored(path)
            if stored.superseded:
                result.superseded.append(stored)
            elif path.name == this_month:
                result.current = stored
            else:
                result.earlier.append(stored)
        result.superseded.sort(key=lambda f: f.name, reverse=True)
        result.earlier.sort(key=lambda f: f.name, reverse=True)
        return result


def _run_order(run: Path) -> str:
    """`20261021T101500` and `recorded-20261021T101500` sort by their time."""
    return run.name.removeprefix("recorded-")


def _stored(path: Path) -> StoredFolder:
    files = []
    for child in path.iterdir():
        # Word's "~$name.docx" and LibreOffice's ".~lock" files appear while a
        # document is open; counting them would report documents that are not there.
        if child.is_file() and not child.name.startswith((".", "~$")):
            files.append(
                StoredFile(child.name, datetime.fromtimestamp(child.stat().st_mtime))
            )
    files.sort(key=lambda f: f.name)
    return StoredFolder(
        name=path.name,
        month=path.name[:7],
        superseded=docs.is_superseded(path),
        files=tuple(files),
    )
