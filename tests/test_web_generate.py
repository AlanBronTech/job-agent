"""User Story 2: generate from a button, with every CLI guard. No network.

The builders are faked; `SyncRunner` does the work inline, so the page after
the POST already shows the outcome.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from jobagent.config import Config
from jobagent.core import store
from jobagent.core.generate import GenerateError, UnusedEntry
from jobagent.core.validation import Severity, ValidationIssue
from jobagent.services import documents, runs
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from jobagent.web.runner import SyncRunner
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
    """Fake builders. `calls` proves whether the model was reached at all."""
    state = SimpleNamespace(calls=[], issues=[], letter_fails=False, clients=0)
    unused = [
        UnusedEntry(id="role_b", group="roles", label="An older role", strong=False, highlight_only=False),
        UnusedEntry(id="venture", group="founder", label="An ongoing venture", strong=True, highlight_only=True),
    ]

    def get_client(*a, **k):
        state.clients += 1
        return object()

    def build_resume(jd, profile, assessment, *, client, today):
        state.calls.append("resume")
        return SimpleNamespace(content="resume", issues=list(state.issues), unused=unused)

    def build_cover_letter(jd, profile, assessment, *, client):
        state.calls.append("cover")
        if state.letter_fails:
            raise GenerateError("the stream closed")
        return SimpleNamespace(text="One.\n\nTwo.", issues=[])

    def write(content, path):
        path.write_bytes(b"docx")
        return path

    monkeypatch.setattr(documents, "get_client", get_client)
    monkeypatch.setattr(documents, "build_resume", build_resume)
    monkeypatch.setattr(documents, "build_cover_letter", build_cover_letter)
    monkeypatch.setattr(documents, "write_resume", write)
    monkeypatch.setattr(documents, "write_cover_letter", write)
    return state


@pytest.fixture
def client(ws, config):
    app = create_app(workspace_factory=lambda: ws, config=config, port=PORT, token=TOKEN,
                     runner=SyncRunner(), today=lambda: TODAY)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    return c


def confirm(client, jd_id, **fields):
    data = {"csrf": TOKEN, "resume": "1", "cover": "1", **fields}
    return client.post(f"/ads/{jd_id}/generate/confirm", data=data)


def start(client, jd_id, **fields):
    data = {"csrf": TOKEN, "resume": "1", "cover": "1", "confirmed": "1", **fields}
    return client.post(f"/ads/{jd_id}/generate", data=data)


# -- Scenario 1: the cost first, nothing spent until confirmed ---------------


def test_the_ad_page_offers_generate(client, ids):
    assert "Review cost and generate" in client.get(f"/ads/{ids['acme']}").text
    assert "Review cost and generate" not in client.get(f"/ads/{ids['contoso']}").text  # not scored


def test_confirm_shows_cost_and_files_and_spends_nothing(client, ids, model):
    page = confirm(client, ids["acme"])
    body = flat(page)
    assert page.status_code == 200
    assert "Expected cost ~$" in body and "claude-sonnet-5" in body
    assert "AlanBron_Resume_AcmeLogistics_202609.docx" in body
    assert "Confirm and generate" in body
    assert model.clients == 0 and model.calls == []


def test_a_start_without_confirmation_starts_nothing(client, ws, ids, model):
    response = client.post(f"/ads/{ids['acme']}/generate",
                           data={"csrf": TOKEN, "resume": "1"})
    assert response.status_code == 409
    assert "confirm the cost first" in flat(response)
    assert model.clients == 0 and runs.last_run_for(ws, ids["acme"]) is None


def test_a_confirmed_run_writes_and_shows_the_outcome(client, ws, ids, model):
    response = start(client, ids["acme"])
    assert response.status_code == 303 and response.headers["location"] == f"/ads/{ids['acme']}"
    assert model.calls == ["resume", "cover"]
    page = flat(client.get(f"/ads/{ids['acme']}"))
    assert "Generating documents finished" in page
    assert "AlanBron_CoverLetter_AcmeLogistics_202609.docx" in page
    assert "No validation issues." in page
    run = runs.last_run_for(ws, ids["acme"])
    assert run.status == "succeeded" and run.result["written"][-1] == "job-ad.md"


# -- Scenario 2: existing documents are moved aside, never overwritten --------


def test_a_clash_is_shown_and_refused_without_supersede(client, ws, ids, model):
    start(client, ids["acme"])
    folder = runs.last_run_for(ws, ids["acme"]).result["folder"]
    resume = ws.documents.output_dir / folder / "AlanBron_Resume_AcmeLogistics_202609.docx"
    resume.write_bytes(b"edited by hand")
    model.calls.clear()

    body = flat(confirm(client, ids["acme"]))
    assert "Already generated." in body and "moved aside under a dated name" in body

    refused = start(client, ids["acme"])
    assert refused.status_code == 409 and model.calls == []
    assert resume.read_bytes() == b"edited by hand"

    start(client, ids["acme"], supersede="1")
    assert model.calls == ["resume", "cover"]
    moved = [p for p in ws.documents.output_dir.iterdir() if ".superseded-" in p.name]
    assert len(moved) == 1
    assert (moved[0] / resume.name).read_bytes() == b"edited by hand"
    assert "superseded" in client.get(f"/ads/{ids['acme']}").text


# -- Scenario 3: a skip needs an explicit overrule, and it is recorded --------


def test_skip_needs_an_overrule_which_is_recorded(client, ws, ids, model):
    body = flat(confirm(client, ids["northwind"]))
    assert "The assessment says skip." in body and "generate anyway" in body

    refused = start(client, ids["northwind"])
    assert refused.status_code == 409 and model.calls == []

    start(client, ids["northwind"], overrule="1")
    assert model.calls == ["resume", "cover"]
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["northwind"]).overrode_scorer


# -- Scenario 4: a blocker is prominent and the set is not presented as ready -


def test_a_blocker_marks_the_set_not_ready(client, ids, model):
    model.issues = [ValidationIssue(rule="unsupported_number", severity=Severity.blocker,
                                    detail="180 is not in the profile.", excerpt="led 180 engineers")]
    start(client, ids["acme"])
    body = flat(client.get(f"/ads/{ids['acme']}"))
    assert "not ready: blocker" in body
    assert body.index("Blockers") < body.index("Not used")
    assert "unsupported_number" in body and "led 180 engineers" in body


# -- Scenario 5: the unused list on a clean run, ongoing venture first --------


def test_unused_entries_shown_on_a_clean_run_venture_first(client, ids, model):
    start(client, ids["acme"])
    body = flat(client.get(f"/ads/{ids['acme']}"))
    assert "No validation issues." in body and "Not used" in body
    assert body.index("An ongoing venture") < body.index("An older role")
    assert "a CAREER HIGHLIGHT is its only slot" in body


# -- failures, repeats and missing setup --------------------------------------


def test_a_letter_failure_after_the_resume_lists_it_as_incomplete(client, ws, ids, model):
    model.letter_fails = True
    start(client, ids["acme"])
    run = runs.last_run_for(ws, ids["acme"])
    assert run.status == "failed"
    assert "Could not write the cover letter: the stream closed" in run.error
    assert "incomplete: AlanBron_Resume_AcmeLogistics_202609.docx" in run.error
    assert "incomplete" in flat(client.get(f"/ads/{ids['acme']}"))


def test_a_run_already_going_is_not_started_twice(client, ws, ids, model):
    runs.start_run(ws, kind="score", jd_id=ids["acme"], run_id="r", request={})
    response = start(client, ids["acme"])
    assert response.status_code == 303 and model.calls == []
    assert len([r for r in runs.running(ws)]) == 1


def test_nothing_selected_goes_back_to_the_ad(client, ids, model):
    response = client.post(f"/ads/{ids['acme']}/generate/confirm", data={"csrf": TOKEN})
    assert response.status_code == 409 and "Choose at least one document" in flat(response)


def test_missing_setup_is_named_and_blocks_confirm(client, ws, ids, model, config, tmp_path):
    bare = Config(_env_file=None, db_path=config.db_path, runs_log_path=config.runs_log_path)
    no_profile = Workspace(**{**ws.__dict__, "profile_dir": None})
    app = create_app(workspace_factory=lambda: no_profile, config=bare, port=PORT, token=TOKEN,
                     runner=SyncRunner(), today=lambda: TODAY)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    body = flat(c.post(f"/ads/{ids['acme']}/generate/confirm",
                       data={"csrf": TOKEN, "resume": "1"}))
    assert "Cannot run yet." in body and "No profile directory" in body
    assert "No model configured" in body
    assert "Confirm and generate" not in body
    refused = c.post(f"/ads/{ids['acme']}/generate", data={"csrf": TOKEN, "resume": "1", "confirmed": "1"})
    assert refused.status_code == 409 and model.clients == 0


def test_ui_runs_are_logged_as_source_ui(client, ids, model, monkeypatch):
    seen = []
    real = documents.generate

    def spy(ws, config, ctx, *a, **k):
        seen.append((ctx.source, ctx.command, ctx.jd_id))
        return real(ws, config, ctx, *a, **k)

    monkeypatch.setattr(documents, "generate", spy)
    start(client, ids["acme"])
    assert seen == [("ui", "generate", ids["acme"])]
