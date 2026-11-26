"""Spec 005 in the UI: the resume choice, the confirm page, recording what went.

Invented data; no network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobagent.core import store
from jobagent.core.generate import GeneratedText, Sentence
from jobagent.services import documents
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from jobagent.web.runner import SyncRunner
from tests.test_agency_resume import build_master, texts
from tests.test_web_generate import PORT, TOKEN, config, flat, model  # noqa: F401 - fixtures
from tests.ui_seed import TODAY, masters_profile, seed, workspace


@pytest.fixture
def ws(tmp_path, config):  # noqa: F811
    profile = masters_profile(tmp_path)
    for name in ("Sam-Resume-Manager.docx", "Sam-Resume-AI.docx", "Sam-Resume-Contract.docx"):
        build_master(profile / "resumes" / name)
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


@pytest.fixture
def profile_writer(monkeypatch, model):  # noqa: F811
    def build_profile(jd, profile, assessment, *, client, **_):
        model.calls.append("profile")
        paragraphs = [[Sentence(text="I run engineering teams that ship.", cites=["recent_manager"])]]
        return GeneratedText(text=paragraphs[0][0].text, paragraphs=paragraphs)

    monkeypatch.setattr(documents, "build_profile", build_profile)
    monkeypatch.setattr(documents.checks, "check_claims", lambda *a, **k: [])
    return model


def folder_files(ws):
    return sorted(p.name for p in ws.documents.output_dir.glob("*/*") if p.is_file())


def test_confirm_names_the_longer_profile_and_its_cost(client, ids, profile_writer):
    data = {"csrf": TOKEN, "resume_kind": "master_profile", "master": "manager"}
    page = flat(client.post(f"/ads/{ids['acme']}/generate/confirm", data=data))
    assert "copy of the Engineering Manager master with a longer profile" in page
    assert "generate_profile" in page  # unmeasured: named in the cost line
    assert "Sam-Resume-Manager.pdf" not in page
    assert "Confirm and generate" in page


def test_master_with_longer_profile_writes_the_copy_and_no_letter(client, ws, ids, profile_writer):
    data = {"csrf": TOKEN, "resume_kind": "master_profile", "master": "manager", "confirmed": "1"}
    assert client.post(f"/ads/{ids['acme']}/generate", data=data).status_code == 303
    files = folder_files(ws)
    assert any("_Resume_" in f for f in files)
    assert not any("CoverLetter" in f for f in files)
    assert not any(f.startswith("Sam-Resume") for f in files)
    assert profile_writer.calls == ["profile"]
    resume = next(ws.documents.output_dir.glob("*/*_Resume_*.docx"))
    assert "I run engineering teams that ship." in texts(resume)


def test_custom_with_longer_profile_reaches_the_resume_call(client, ws, ids, profile_writer, monkeypatch):
    seen = {}
    original = documents.build_resume

    def build_resume(*a, long_profile=False, **k):
        seen["long_profile"] = long_profile
        return original(*a, **k)

    monkeypatch.setattr(documents, "build_resume", build_resume)
    data = {"csrf": TOKEN, "resume_kind": "custom_profile", "confirmed": "1"}
    assert client.post(f"/ads/{ids['acme']}/generate", data=data).status_code == 303
    assert seen == {"long_profile": True}


def test_an_unknown_resume_choice_is_refused(client, ws, ids, profile_writer):
    data = {"csrf": TOKEN, "resume_kind": "executive"}
    page = client.post(f"/ads/{ids['acme']}/generate/confirm", data=data)
    assert page.status_code == 409 and "executive" in flat(page)
    assert folder_files(ws) == []


def test_a_master_without_a_profile_section_is_refused_on_confirm(client, ws, ids, profile_writer):
    build_master(ws.profile_dir / "resumes" / "Sam-Resume-AI.docx", profile_heading=None)
    data = {"csrf": TOKEN, "resume_kind": "master_profile", "master": "ai"}
    page = client.post(f"/ads/{ids['acme']}/generate/confirm", data=data)
    assert page.status_code == 409 and "PROFILE" in flat(page)
    assert profile_writer.calls == []


def test_pipeline_records_the_longer_profile(client, ws, ids):
    data = {"csrf": TOKEN, "status": "applied", "master": "manager+profile"}
    assert client.post(f"/ads/{ids['acme']}/pipeline", data=data).status_code in (200, 303)
    with store.open_store(ws.db_path) as conn:
        application = store.get_application(conn, ids["acme"])
    assert (application.resume_master, application.resume_long_profile) == ("manager", True)
    assert "Engineering Manager master with a longer profile" in flat(client.get(f"/ads/{ids['acme']}"))


def test_pipeline_offers_the_longer_profile_choices(client, ids):
    page = client.get(f"/ads/{ids['acme']}").text
    assert '<option value="manager+profile">' in page
    assert '<option value="custom+profile">' in page
