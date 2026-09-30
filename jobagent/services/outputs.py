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
from jobagent.core.models import JobDescription
from jobagent.services.workspace import Workspace


def documents_for(ws: Workspace, jd: JobDescription, today: date) -> OutputFolders:
    return ws.documents.list_for(jd, today)


def index_all(
    ws: Workspace, jds: Iterable[JobDescription], today: date
) -> dict[int, OutputFolders]:
    """Folders for every ad at once, from one listing of the output folder."""
    return ws.documents.index(jds, today)
