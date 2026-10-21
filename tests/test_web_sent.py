"""The pipeline form records what was sent; the diff page shows how far it moved.

REVIEW-2026-10-18 task 1, in the UI. Invented data; no model client is built.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from jobagent.adapters import docs, llm
from jobagent.adapters.docx_writer import write_resume
from jobagent.core import store
from jobagent.web.app import create_app
from tests.test_sent import resume_content
from tests.ui_seed import TODAY, seed, workspace

PORT = 8765
TOKEN = "test-token"


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("recording what was sent built a model client")
    monkeypatch.setattr(llm, "get_client", refuse)


@pytest.fixture
def ws(tmp_path):
    return workspace(tmp_path)


@pytest.fixture
def ids(ws):
    return seed(ws)


@pytest.fixture
def client(ws):
    app = create_app(workspace_factory=lambda: ws, config=None, port=PORT, token=TOKEN,
                     today=lambda: TODAY)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    return c


@pytest.fixture
def generated(ws, ids, tmp_path):
    """Acme's resume as `generate` leaves it, and an edited copy of it."""
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, ids["acme"])
    name = docs.document_name("Resume", jd, when=TODAY)
    write_resume(resume_content(), ws.documents.path_for_write(jd, TODAY, name))
    ws.documents.keep_generated(jd, TODAY, name, datetime(2026, 9, 29, 14, 0, 0))
    edited = write_resume(
        resume_content(profile_paragraphs=["Leads teams that ship weekly.", "Twelve engineers at the last role."]),
        tmp_path / name,
    )
    return name, edited.read_bytes()


def sent_rows(ws, jd_id):
    with store.open_store(ws.db_path) as conn:
        return store.list_sent(conn, jd_id)


def test_the_form_offers_the_sent_files(client, ids):
    page = client.get(f"/ads/{ids['acme']}").text
    assert 'enctype="multipart/form-data"' in page
    assert 'name="sent_resume"' in page and 'name="sent_as_generated"' in page


def test_applied_with_the_sent_resume_records_both(client, ws, ids, generated):
    name, data = generated
    saved = client.post(
        f"/ads/{ids['acme']}/pipeline",
        data={"csrf": TOKEN, "status": "applied", "applied_on": "2026-09-28"},
        files={"sent_resume": (name, data)},
    )
    assert saved.status_code == 303, saved.text
    (row,) = sent_rows(ws, ids["acme"])
    assert row.name == f"sent/2026-09-28/{name}" and not row.as_generated
    page = client.get(f"/ads/{ids['acme']}").text
    assert "of generated words kept" in page and f"/ads/{ids['acme']}/diff" in page


def test_the_diff_page_shows_the_changed_sentence(client, ws, ids, generated):
    name, data = generated
    client.post(f"/ads/{ids['acme']}/pipeline", data={"csrf": TOKEN, "status": "applied"},
                files={"sent_resume": (name, data)})
    page = client.get(f"/ads/{ids['acme']}/diff").text
    assert "Leads teams that ship weekly." in page and "<del>Leads teams that ship.</del>" in page


def test_sent_unedited_needs_no_files(client, ws, ids, generated):
    saved = client.post(f"/ads/{ids['acme']}/pipeline",
                        data={"csrf": TOKEN, "status": "applied", "sent_as_generated": "1"})
    assert saved.status_code == 303
    (row,) = sent_rows(ws, ids["acme"])
    assert row.as_generated
    assert "unedited" in client.get(f"/ads/{ids['acme']}").text


def test_files_without_a_status_record_the_files_and_no_application(client, ws, ids, generated):
    """Sending documents does not imply Applied (REVIEW-2026-10-16 D9)."""
    name, data = generated
    saved = client.post(f"/ads/{ids['acme']}/pipeline", data={"csrf": TOKEN, "status": ""},
                        files={"sent_resume": (name, data)})
    assert saved.status_code == 303
    assert len(sent_rows(ws, ids["acme"])) == 1
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["acme"]) is None


def test_a_refused_status_copies_nothing(client, ws, ids, generated):
    name, data = generated
    refused = client.post(f"/ads/{ids['acme']}/pipeline", data={"csrf": TOKEN, "status": "hired"},
                          files={"sent_resume": (name, data)})
    assert refused.status_code == 409
    assert sent_rows(ws, ids["acme"]) == []
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, ids["acme"])
    folder = ws.documents.output_dir / ws.documents.list_for(jd, TODAY).current.name
    assert not (folder / "sent").exists()


def test_a_wrong_kind_of_file_is_refused_and_records_nothing(client, ws, ids):
    refused = client.post(f"/ads/{ids['acme']}/pipeline", data={"csrf": TOKEN, "status": "applied"},
                          files={"sent_resume": ("notes.txt", b"hello")})
    assert refused.status_code == 409 and "expected .docx or .pdf" in refused.text
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["acme"]) is None


def test_unedited_with_nothing_generated_is_refused(client, ws, ids):
    refused = client.post(f"/ads/{ids['acme']}/pipeline",
                          data={"csrf": TOKEN, "status": "applied", "sent_as_generated": "1"})
    assert refused.status_code == 409 and "no generated copy" in refused.text
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["acme"]) is None
