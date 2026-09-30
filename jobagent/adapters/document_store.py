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
