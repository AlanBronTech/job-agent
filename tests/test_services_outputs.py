"""services.outputs: current, superseded and earlier folders count as done."""

from __future__ import annotations

from datetime import date, datetime, timezone

from jobagent.adapters.document_store import LocalFolderStore
from jobagent.core.models import JobDescription, WorkArrangement, WorkType
from jobagent.services import outputs
from jobagent.services.workspace import Workspace

TODAY = date(2026, 9, 29)


def make_ws(tmp_path) -> Workspace:
    return Workspace(
        owner="local",
        profile_dir=None,
        db_path=tmp_path / "db",
        runs_log_path=tmp_path / "runs.jsonl",
        jd_dir=tmp_path / "jds",
        documents=LocalFolderStore(tmp_path / "out"),
    )


def make_jd(jd_id: int, company: str) -> JobDescription:
    return JobDescription(
        id=jd_id,
        title="Engineering Manager",
        company=company,
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        raw_text="An invented ad. " * 40,
        ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


def test_only_a_superseded_folder_still_counts(tmp_path):
    ws = make_ws(tmp_path)
    jd = make_jd(1, "Acme Logistics")
    ws.documents.path_for_write(jd, TODAY, "r.docx").write_bytes(b"sent")
    ws.documents.supersede(jd, TODAY, datetime(2026, 9, 29, 9, 0, 0))
    folders = outputs.documents_for(ws, jd, TODAY)
    assert folders.current is None
    assert len(folders.superseded) == 1
    assert folders.any


def test_only_an_earlier_month_still_counts(tmp_path):
    ws = make_ws(tmp_path)
    jd = make_jd(1, "Acme Logistics")
    ws.documents.path_for_write(jd, date(2026, 7, 14), "r.docx").write_bytes(b"x")
    folders = outputs.documents_for(ws, jd, TODAY)
    assert folders.current is None and [f.month for f in folders.earlier] == ["2026-07"]
    assert folders.any


def test_index_all(tmp_path):
    ws = make_ws(tmp_path)
    acme, northwind = make_jd(1, "Acme Logistics"), make_jd(2, "Northwind Freight")
    ws.documents.path_for_write(northwind, TODAY, "r.docx").write_bytes(b"x")
    index = outputs.index_all(ws, [acme, northwind], TODAY)
    assert not index[1].any and index[2].any
