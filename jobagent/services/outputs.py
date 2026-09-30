"""What is on disk for an ad: the "has this been done" answer.

The store is not the record of what has been done; documents on disk are.
`generate` once rewrote a folder three days after it was written because the
database had no application row. So anything that asks whether an ad has been
worked on asks here, and superseded and earlier-month folders count.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from jobagent.adapters.document_store import OutputFolders
from jobagent.core import store
from jobagent.core.models import JobDescription
from jobagent.services.refusals import NoSuchAd
from jobagent.services.workspace import Workspace


def documents_for(ws: Workspace, jd: JobDescription, today: date) -> OutputFolders:
    return ws.documents.list_for(jd, today)


def index_all(
    ws: Workspace, jds: Iterable[JobDescription], today: date
) -> dict[int, OutputFolders]:
    """Folders for every ad at once, from one listing of the output folder."""
    return ws.documents.index(jds, today)


def open_document(ws: Workspace, jd_id: int, folder: str, name: str, today: date) -> None:
    """Open one listed document for review. Raises NoSuchAd or FileNotFoundError."""
    ws.documents.open(_jd(ws, jd_id), folder, name, today)


def reveal_folder(ws: Workspace, jd_id: int, folder: str, today: date) -> None:
    ws.documents.reveal(_jd(ws, jd_id), folder, today)


def _jd(ws: Workspace, jd_id: int) -> JobDescription:
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
    if jd is None:
        raise NoSuchAd(jd_id)
    return jd
