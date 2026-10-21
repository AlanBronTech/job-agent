"""Revise and context in the UI: confirm, then a run; the note and context reach the writer.

Builders faked; `SyncRunner` does the work inline. Invented data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from jobagent.adapters.docx_writer import write_resume
from jobagent.config import Config
from jobagent.core import store
from jobagent.services import documents, revise
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from jobagent.web.runner import SyncRunner
from tests.test_sent import resume_content
from tests.ui_seed import TODAY, seed, workspace

PORT = 8765
TOKEN = "test-token"
EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"


def flat(response) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", response.text).split())


@pytest.fixture
def config(tmp_path):
    runs_log = tmp_path / "runs.jsonl"
    runs_log.write_text("".join(
        json.dumps({"label": label, "model": "claude-sonnet-5", "input_tokens": 20_000,
                    "output_tokens": 4_000, "cost_usd": 0.1, "price_unknown": False,
                    "run_id": "past", "outcome": "ok"}) + "\n"
        for label in ["generate_resume", "generate_cover_letter"]
    ))
    return Config(_env_file=None, db_path=tmp_path / "jobagent.db", runs_log_path=runs_log,
                  llm_default="anthropic:claude-sonnet-5", anthropic_api_key="test-key")


@pytest.fixture
def ws(tmp_path, config):
    base = workspace(tmp_path)
    return Workspace(**{**base.__dict__, "profile_dir": EXAMPLE_PROFILE,
                        "runs_log_path": config.runs_log_path})


@pytest.fixture
def ids(ws):
    return seed(ws)


@pytest.fixture
def model(monkeypatch):
    seen = []

    def build_resume(jd, profile, assessment, *, client, today, instructions=None, **_):
        seen.append(instructions)
        return SimpleNamespace(content=resume_content(), issues=[], unused=[])

    monkeypatch.setattr(documents, "get_client", lambda *a, **k: object())
    monkeypatch.setattr(documents.role_kind, "ensure", lambda *a, **k: None)
    monkeypatch.setattr(documents, "build_resume", build_resume)
    return seen


@pytest.fixture
def client(ws, config):
    app = create_app(workspace_factory=lambda: ws, config=config, port=PORT, token=TOKEN,
                     runner=SyncRunner(), today=lambda: TODAY)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    return c


@pytest.fixture
def generated(client, ids, model):
    """Acme's resume, generated through the UI."""
    client.post(f"/ads/{ids['acme']}/generate", data={
        "csrf": TOKEN, "resume": "1", "confirmed": "1", "checks_shown": "1"})
    assert model, "the generate run did not reach the builder"
    return ids["acme"]


def test_the_page_offers_a_revision_once_there_is_something_to_revise(client, ids, generated):
    page = client.get(f"/ads/{generated}").text
    assert f'action="/ads/{generated}/revise/confirm"' in page and 'name="note"' in page
    assert f'action="/ads/{ids["contoso"]}/revise/confirm"' not in client.get(f"/ads/{ids['contoso']}").text


def test_confirm_shows_the_cost_and_spends_nothing(client, generated, model):
    calls = len(model)
    page = client.post(f"/ads/{generated}/revise/confirm",
                       data={"csrf": TOKEN, "kind": "resume", "note": "Say weekly."})
    assert page.status_code == 200 and "Cost:" in flat(page) and "Say weekly." in page.text
    assert len(model) == calls


def test_a_confirmed_revision_runs_with_the_note(client, ws, generated, model):
    done = client.post(f"/ads/{generated}/revise",
                       data={"csrf": TOKEN, "kind": "resume", "note": "Say weekly.", "confirmed": "1"})
    assert done.status_code == 303
    assert "Say weekly." in model[-1] and "Leads teams that ship." in model[-1]
    assert [n.note for n in revise.notes(ws, generated)] == ["Say weekly."]
    assert "Revised: “Say weekly.”" in client.get(f"/ads/{generated}").text


def test_an_empty_note_is_refused(client, generated):
    page = client.post(f"/ads/{generated}/revise/confirm", data={"csrf": TOKEN, "kind": "resume", "note": ""})
    assert page.status_code == 409 and "needs a note" in page.text


def test_a_hand_edit_needs_the_box_ticked(client, ws, generated, model):
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, generated)
    current = ws.documents.list_for(jd, TODAY).current
    visible = ws.documents.output_dir / current.name / current.files[0].name
    write_resume(resume_content(profile_paragraphs=["Edited by hand."]), visible)
    calls = len(model)
    refused = client.post(f"/ads/{generated}/revise",
                          data={"csrf": TOKEN, "kind": "resume", "note": "x", "confirmed": "1"})
    assert refused.status_code == 409 and 'name="replace_edits"' in refused.text
    assert len(model) == calls


def test_context_is_saved_and_reaches_the_next_writer(client, ws, ids, model):
    client.post(f"/ads/{ids['acme']}/context", data={"csrf": TOKEN, "context": "Recruiter said payments."})
    assert "Recruiter said payments." in client.get(f"/ads/{ids['acme']}").text
    client.post(f"/ads/{ids['acme']}/generate", data={
        "csrf": TOKEN, "resume": "1", "confirmed": "1", "checks_shown": "1"})
    assert "Recruiter said payments." in model[-1]
