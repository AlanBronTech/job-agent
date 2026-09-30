"""LocalFolderStore: listing, superseding and opening, by folder and file name."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from jobagent.adapters.document_store import LocalFolderStore
from jobagent.core.models import JobDescription, WorkArrangement, WorkType

TODAY = date(2026, 9, 29)
NOW = datetime(2026, 9, 29, 14, 5, 12)


def make_jd(jd_id: int, company: str = "Acme Logistics") -> JobDescription:
    return JobDescription(
        id=jd_id,
        title="Engineering Manager",
        company=company,
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        raw_text="An invented ad. " * 40,
        ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, args, check):
        self.calls.append(args)


@pytest.fixture
def run():
    return FakeRun()


@pytest.fixture
def store(tmp_path, run):
    return LocalFolderStore(tmp_path / "out", run=run)


def test_nothing_on_disk(store):
    folders = store.list_for(make_jd(1), TODAY)
    assert folders.current is None and folders.all == [] and not folders.any


def test_current_superseded_and_earlier(store):
    jd = make_jd(1)
    store.path_for_write(jd, date(2026, 8, 3), "a.docx").write_bytes(b"august")
    store.path_for_write(jd, TODAY, "b.docx").write_bytes(b"first")
    moved = store.supersede(jd, TODAY, NOW)
    store.path_for_write(jd, TODAY, "b.docx").write_bytes(b"second")

    folders = store.list_for(jd, TODAY)
    assert folders.current.name == "2026-09_AcmeLogistics_EngineeringManager"
    assert [f.name for f in folders.superseded] == [moved]
    assert [f.name for f in folders.earlier] == ["2026-08_AcmeLogistics_EngineeringManager"]
    assert folders.any


def test_supersede_with_nothing_there_is_none(store):
    assert store.supersede(make_jd(1), TODAY, NOW) is None


def test_markdown_alone_is_not_documents(store):
    jd = make_jd(1)
    store.write_text(jd, TODAY, "interview-prep.md", "# prep")
    folders = store.list_for(jd, TODAY)
    assert folders.current is not None and not folders.any


def test_office_lock_files_are_not_documents(store):
    jd = make_jd(1)
    store.path_for_write(jd, TODAY, "~$resume.docx").write_bytes(b"lock")
    store.path_for_write(jd, TODAY, ".~lock.resume.docx#").write_bytes(b"lock")
    folders = store.list_for(jd, TODAY)
    assert folders.current.files == () and not folders.any


def test_index_keeps_ads_apart(store):
    acme, northwind = make_jd(1), make_jd(2, company="Northwind Freight")
    store.path_for_write(acme, TODAY, "r.docx").write_bytes(b"x")
    index = store.index([acme, northwind], TODAY)
    assert index[1].any and not index[2].any


def test_open_and_reveal_by_name(store, run):
    jd = make_jd(1)
    path = store.path_for_write(jd, TODAY, "r.docx")
    path.write_bytes(b"x")
    store.open(jd, path.parent.name, "r.docx", TODAY)
    store.reveal(jd, path.parent.name, TODAY)
    assert run.calls == [
        ["open", str(path.resolve())],
        ["open", "-R", str(path.parent.resolve())],
    ]


def test_open_refuses_a_folder_belonging_to_another_ad(store, run):
    acme, northwind = make_jd(1), make_jd(2, company="Northwind Freight")
    other = store.path_for_write(northwind, TODAY, "r.docx")
    other.write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        store.open(acme, other.parent.name, "r.docx", TODAY)
    with pytest.raises(FileNotFoundError):
        store.open(acme, "../elsewhere", "r.docx", TODAY)
    assert run.calls == []


def test_open_refuses_a_file_not_listed(store, run):
    jd = make_jd(1)
    path = store.path_for_write(jd, TODAY, "r.docx")
    path.write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        store.open(jd, path.parent.name, "../../etc/passwd", TODAY)
    assert run.calls == []
