"""The pipeline form records which master resume went. Invented data; free."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobagent.adapters import llm
from jobagent.core import store
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from tests.ui_seed import TODAY, masters_profile, seed, workspace

PORT = 8765
TOKEN = "test-token"


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("recording a master built a model client")
    monkeypatch.setattr(llm, "get_client", refuse)


@pytest.fixture
def ws(tmp_path):
    return Workspace(**{**workspace(tmp_path).__dict__, "profile_dir": masters_profile(tmp_path)})


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


def application(ws, jd_id):
    with store.open_store(ws.db_path) as conn:
        return store.get_application(conn, jd_id)


def sent_names(ws, jd_id):
    with store.open_store(ws.db_path) as conn:
        return [r.name.split("/")[-1] for r in store.list_sent(conn, jd_id)]


def post(client, jd_id, **data):
    return client.post(f"/ads/{jd_id}/pipeline", data={"csrf": TOKEN, **data})


def test_the_form_offers_the_masters_with_the_suggestion_marked(client, ids):
    page = client.get(f"/ads/{ids['acme']}").text
    assert 'name="master"' in page
    assert "Engineering Manager (suggested)" in page
    assert "AI adoption lead" in page and "A custom resume" in page


def test_choosing_a_master_records_it_and_keeps_its_file(client, ws, ids):
    saved = post(client, ids["acme"], status="applied", master="ai")
    assert saved.status_code == 303
    app = application(ws, ids["acme"])
    assert (app.resume_master, app.resume_suggested) == ("ai", "manager")
    assert sent_names(ws, ids["acme"]) == ["Sam-Resume-AI.docx"]


def test_applied_with_no_master_chosen_assumes_nothing(client, ws, ids):
    post(client, ids["acme"], status="applied")
    assert application(ws, ids["acme"]).resume_master is None
    assert sent_names(ws, ids["acme"]) == []


def test_an_unknown_master_saves_nothing(client, ws, ids):
    saved = post(client, ids["acme"], status="applied", master="executive")
    assert saved.status_code == 409 and "executive" in saved.text
    assert application(ws, ids["acme"]) is None


def test_the_recorded_resume_is_shown(client, ws, ids):
    post(client, ids["acme"], status="applied", master="custom")
    import re

    page = re.sub(r"<[^>]+>", " ", client.get(f"/ads/{ids['acme']}").text)
    assert "Resume sent: a custom resume" in " ".join(page.split())


def test_an_uploaded_copy_of_a_master_is_that_master(client, ws, ids):
    data = (ws.profile_dir / "resumes" / "Sam-Resume-Manager.pdf").read_bytes()
    post_files = client.post(
        f"/ads/{ids['acme']}/pipeline",
        data={"csrf": TOKEN, "status": "applied"},
        files={"sent_resume": ("Resume.pdf", data, "application/pdf")},
    )
    assert post_files.status_code == 303
    assert application(ws, ids["acme"]).resume_master == "manager"
