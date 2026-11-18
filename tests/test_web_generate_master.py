"""The generate form with master resumes: the recommended master ticked and
copied into the job folder for free, a custom resume offered unticked with
advice on whether it is worth it. Invented data; no network."""

from __future__ import annotations

import pytest
from docx import Document
from fastapi.testclient import TestClient

from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from jobagent.web.runner import SyncRunner
from tests.test_web_generate import PORT, TOKEN, config, flat, model  # noqa: F401 - fixtures
from tests.ui_seed import TODAY, masters_profile, seed, workspace


@pytest.fixture
def ws(tmp_path, config):  # noqa: F811
    profile = masters_profile(tmp_path)
    master = Document()
    master.add_paragraph("Engineering Manager · Example Manufacturing Co")
    master.save(profile / "resumes" / "Sam-Resume-Manager.docx")
    base = workspace(tmp_path)
    return Workspace(**{**base.__dict__, "profile_dir": profile,
                        "runs_log_path": config.runs_log_path})


@pytest.fixture
def ids(ws):
    return seed(ws)


@pytest.fixture
def client(ws, config):  # noqa: F811
    app = create_app(workspace_factory=lambda: ws, config=config, port=PORT, token=TOKEN,
                     runner=SyncRunner(), today=lambda: TODAY)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    return c


def folder_files(ws):
    return sorted(p.name for p in ws.documents.output_dir.glob("*/*") if p.is_file())


def test_the_form_ticks_the_recommended_master_and_the_letter_not_custom(client, ids):
    page = " ".join(client.get(f"/ads/{ids['acme']}").text.split())
    assert '<input type="checkbox" name="use_master" value="1" checked>' in page
    assert '<option value="manager" selected>Engineering Manager (recommended)</option>' in page
    assert '<input type="checkbox" name="resume" value="1" > Custom resume' in page
    assert '<input type="checkbox" name="cover" value="1" checked>' in page
    assert "Not recommended:" in flat(client.get(f"/ads/{ids['acme']}"))


def test_master_only_copies_it_into_the_folder_and_calls_no_model(client, ws, ids, model):  # noqa: F811
    data = {"csrf": TOKEN, "use_master": "1", "master": "manager"}
    page = flat(client.post(f"/ads/{ids['acme']}/generate/confirm", data=data))
    assert "Sam-Resume-Manager.pdf" in page and "Confirm and generate" in page
    started = client.post(f"/ads/{ids['acme']}/generate", data={**data, "confirmed": "1"})
    assert started.status_code == 303
    assert model.clients == 0 and model.calls == []
    assert "Sam-Resume-Manager.pdf" in folder_files(ws)
    shown = flat(client.get(f"/ads/{ids['acme']}"))
    assert "copied into the job folder unchanged" in shown and "not reviewed" not in shown


def test_master_and_letter_together(client, ws, ids, model):  # noqa: F811
    data = {"csrf": TOKEN, "use_master": "1", "master": "ai", "cover": "1", "confirmed": "1"}
    assert client.post(f"/ads/{ids['acme']}/generate", data=data).status_code == 303
    files = folder_files(ws)
    assert "Sam-Resume-AI.docx" in files  # no PDF for this master: the .docx
    assert any("CoverLetter" in f for f in files)
    assert model.calls == ["cover"]


def test_an_unknown_master_is_refused_before_anything(client, ws, ids, model):  # noqa: F811
    data = {"csrf": TOKEN, "use_master": "1", "master": "executive"}
    page = client.post(f"/ads/{ids['acme']}/generate/confirm", data=data)
    assert page.status_code == 409 and "executive" in flat(page)
    assert folder_files(ws) == []


def test_master_alone_into_a_folder_that_has_a_letter_moves_nothing(client, ws, ids, model):  # noqa: F811
    first = {"csrf": TOKEN, "cover": "1", "confirmed": "1"}
    assert client.post(f"/ads/{ids['acme']}/generate", data=first).status_code == 303
    before = folder_files(ws)
    data = {"csrf": TOKEN, "use_master": "1", "master": "manager"}
    page = flat(client.post(f"/ads/{ids['acme']}/generate/confirm", data=data))
    assert "Already generated" not in page
    assert client.post(f"/ads/{ids['acme']}/generate",
                       data={**data, "confirmed": "1"}).status_code == 303
    assert folder_files(ws) == sorted(before + ["Sam-Resume-Manager.pdf"])
    # And again: the same file, so no clash and no supersede.
    assert client.post(f"/ads/{ids['acme']}/generate",
                       data={**data, "confirmed": "1"}).status_code == 303
    assert len(list(ws.documents.output_dir.iterdir())) == 1
