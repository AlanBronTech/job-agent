"""The batch page: US1 scenarios, nothing without confirmation, parity. Invented ads."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from jobagent.adapters.adtext import ExtractedAd
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import (
    ApplicationStatus,
    FitAssessment,
    JobDescription,
    Verdict,
    WorkArrangement,
    WorkType,
)
from jobagent.services import ads, batches, scoring
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from jobagent.web.runner import SyncRunner
from tests.ui_seed import TODAY, jd as seed_jd, workspace

PORT = 8765
TOKEN = "test-token"
EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
AD = "Engineering Manager at {co}. An invented advertisement. " * 40


def flat(response) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", response.text).split())


@pytest.fixture
def ws(tmp_path):
    base = workspace(tmp_path)
    ws = Workspace(**{**base.__dict__, "profile_dir": EXAMPLE_PROFILE})
    ws.jd_dir.mkdir()
    with store.open_store(ws.db_path) as conn:
        old = seed_jd("Old role", "Contoso Health", 0)
        old.ingested_at = datetime.now(timezone.utc) - timedelta(hours=2)
        store.add_jd(conn, old)
    return ws


@pytest.fixture
def model(monkeypatch):
    state = SimpleNamespace(parsed=[], scored=[], contexts=[])

    def parse_jd(text, *, client, source):
        state.parsed.append(text)
        company = text.split(" at ")[1].split(".")[0]
        return JobDescription(title="Engineering Manager", company=company,
                              work_type=WorkType.permanent, work_arrangement=WorkArrangement.hybrid,
                              raw_text=text, ingested_at=datetime.now(timezone.utc))

    def score_fit(jd_, profile, *, client):
        state.scored.append(jd_.id)
        return FitAssessment(jd_id=jd_.id, overall_score=72, recruiter_screen_score=64,
                             verdict=Verdict.apply, rationale="Invented rationale.",
                             target_role_match=True, target_role_note="Invented.",
                             scored_at=datetime.now(timezone.utc))

    def client(call_type, config, ctx):
        state.contexts.append((ctx.command, ctx.source, ctx.jd_id))
        return SimpleNamespace(context=ctx)

    real_extract = ads.extract_saved_page

    def extract(file):
        if file.suffix == ".pdf":
            return ExtractedAd(text="Half", full_text="x" * 3000, source_url=None,
                               page_title=None, posting_metadata=None, truncated=True)
        return real_extract(file)

    monkeypatch.setattr(ads, "parse_jd", parse_jd)
    monkeypatch.setattr(ads, "get_client", client)
    monkeypatch.setattr(scoring, "get_client", client)
    monkeypatch.setattr(scoring, "score_fit", score_fit)
    monkeypatch.setattr(ads, "extract_saved_page", extract)
    return state


@pytest.fixture
def client(ws):
    config = Config(_env_file=None, db_path=ws.db_path, runs_log_path=ws.runs_log_path,
                    llm_default="anthropic:claude-sonnet-5", anthropic_api_key="test-key")
    app = create_app(workspace_factory=lambda: ws, config=config, port=PORT, token=TOKEN,
                     runner=SyncRunner(), today=lambda: TODAY)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    return c


def save(ws, name, text):
    path = ws.jd_dir / name
    path.write_text(text)
    now = datetime.now().timestamp()
    os.utime(path, (now, now))


def ids_in(page) -> list[int]:
    return [int(x) for x in re.findall(r'name="jd" value="(\d+)"', page.text)]


# -- scenario 1: files and the combined cost before anything is spent ------------


def test_new_files_and_cost_shown_nothing_spent(client, ws, model):
    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    save(ws, "fabrikam.txt", AD.format(co="Fabrikam Medical"))
    body = flat(client.get("/batch"))
    assert "2 new saved ad(s)" in body and "acme.txt" in body and "fabrikam.txt" in body
    assert "Confirm and parse all" in body
    assert model.parsed == []


def test_parse_needs_confirmation(client, ws, model):
    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    response = client.post("/batch/parse", data={"csrf": TOKEN})
    assert response.status_code == 409 and model.parsed == []


# -- scenario 2: a refused capture is its own row -------------------------------


def test_parse_gives_one_row_per_file_with_the_refusal(client, ws, model):
    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    save(ws, "cutoff.pdf", "%PDF stand-in")
    assert client.post("/batch/parse", data={"csrf": TOKEN, "confirmed": "1"}).status_code == 303
    body = flat(client.get("/batch"))
    assert "Acme Logistics" in body
    assert "cutoff.pdf" in body and "Cut off at" in body and "refused" in body
    assert len(model.parsed) == 1
    runs_sources = [c for c in model.contexts if c[0] == "jd add"]
    assert runs_sources == [("jd add", "ui", None)]


# -- scenario 3: score several, with the combined cost first -------------------


def test_score_selected_confirms_then_scores(client, ws, model):
    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    save(ws, "fabrikam.txt", AD.format(co="Fabrikam Medical"))
    client.post("/batch/parse", data={"csrf": TOKEN, "confirmed": "1"})
    selected = ids_in(client.get("/batch"))
    assert len(selected) == 2

    confirm = flat(client.post("/batch/score/confirm", data={"csrf": TOKEN, "jd": selected}))
    assert "Score 2 ad(s)?" in confirm
    assert "About $" in confirm or "No measurement" in confirm
    assert model.scored == []

    assert client.post("/batch/score", data={"csrf": TOKEN, "jd": selected}).status_code == 409
    assert model.scored == []

    client.post("/batch/score", data={"csrf": TOKEN, "confirmed": "1", "jd": selected})
    assert sorted(model.scored) == sorted(selected)
    body = flat(client.get("/batch"))
    assert body.count("72 / 64") == 2


def test_a_recent_application_is_left_out_of_score_selected(client, ws, model):
    from datetime import date

    from jobagent.core.models import OutsideApplication

    with store.open_store(ws.db_path) as conn:
        store.add_outside(conn, OutsideApplication(
            company="Fabrikam Medical", title="Engineering Manager",
            applied_on=date.today() - timedelta(days=30), status=ApplicationStatus.applied,
            created_at=datetime.now(timezone.utc)))
    save(ws, "fabrikam.txt", AD.format(co="Fabrikam Medical"))
    client.post("/batch/parse", data={"csrf": TOKEN, "confirmed": "1"})
    page = client.get("/batch")
    assert "possibly the same job" in flat(page)
    selected = ids_in(page)
    confirm = flat(client.post("/batch/score/confirm", data={"csrf": TOKEN, "jd": selected}))
    assert "Score 0 ad(s)?" in confirm and "a job you applied for recently" in confirm
    client.post("/batch/score", data={"csrf": TOKEN, "confirmed": "1", "jd": selected})
    assert model.scored == []


# -- scenario 4: mark the rest not applied; generate per ad -----------------------


def test_mark_selected_not_applied_and_rows_link_to_their_ads(client, ws, model):
    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    client.post("/batch/parse", data={"csrf": TOKEN, "confirmed": "1"})
    page = client.get("/batch")
    (jd_id,) = ids_in(page)
    assert f'href="/ads/{jd_id}"' in page.text
    client.post("/batch/skip", data={"csrf": TOKEN, "jd": [jd_id]})
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, jd_id).status is ApplicationStatus.not_applied
    assert "not applied" in flat(client.get("/batch"))


# -- scenario 5 / FR-006: the same rows as the CLI -------------------------------


def test_the_page_shows_the_service_rows(client, ws, model):
    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    save(ws, "cutoff.pdf", "%PDF stand-in")
    client.post("/batch/parse", data={"csrf": TOKEN, "confirmed": "1"})
    rows = batches.rows(ws, batches.latest(ws), TODAY)
    body = flat(client.get("/batch"))
    for r in rows:
        assert r.file_name in body or (r.title and r.title in body)


# -- FR-005 / SC-004: a batch action is the single action ------------------------


def test_scoring_from_a_batch_matches_scoring_singly(client, ws, model):
    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    client.post("/batch/parse", data={"csrf": TOKEN, "confirmed": "1"})
    (from_batch,) = ids_in(client.get("/batch"))
    with store.open_store(ws.db_path) as conn:
        twin = store.get_jd(conn, from_batch)
        twin.id = None
        single = store.add_jd(conn, twin)

    model.contexts.clear()
    client.post("/batch/score", data={"csrf": TOKEN, "confirmed": "1", "jd": [from_batch]})
    client.post(f"/ads/{single}/score", data={"csrf": TOKEN, "confirmed": "1"})

    with store.open_store(ws.db_path) as conn:
        a = store.latest_assessment(conn, from_batch).model_dump(exclude={"id", "jd_id", "scored_at"})
        b = store.latest_assessment(conn, single).model_dump(exclude={"id", "jd_id", "scored_at"})
    assert a == b
    assert [(c, s) for c, s, _ in model.contexts] == [("score", "ui"), ("score", "ui")]
