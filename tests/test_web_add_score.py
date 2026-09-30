"""User Story 3: add and score an ad from the browser. No network, invented ads.

The parser and scorer are faked in the services they are called from;
`SyncRunner` does the work inline, so the redirect after a POST lands on the
finished state.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from jobagent.adapters.adtext import ExtractedAd
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import FitAssessment, JobDescription, Verdict, WorkArrangement, WorkType
from jobagent.services import ads, runs, scoring
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from jobagent.web.runner import SyncRunner
from tests.ui_seed import TODAY, seed, workspace

PORT = 8765
TOKEN = "test-token"
EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
AD = "Engineering Manager at Acme Logistics, Sydney. An invented advertisement. " * 30


def flat(response) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", response.text).split())


@pytest.fixture
def config(tmp_path):
    runs_log = tmp_path / "runs.jsonl"
    runs_log.write_text("".join(
        json.dumps({"label": label, "model": "claude-sonnet-5", "input_tokens": 10_000,
                    "output_tokens": 2_000, "cost_usd": 0.1, "price_unknown": False,
                    "run_id": "past", "outcome": "ok"}) + "\n"
        for label in ["parse_jd", "score_fit"]
    ))
    return Config(_env_file=None, db_path=tmp_path / "jobagent.db", runs_log_path=runs_log,
                  llm_default="anthropic:claude-sonnet-5", anthropic_api_key="test-key")


@pytest.fixture
def ws(tmp_path, config):
    base = workspace(tmp_path)
    ws = Workspace(**{**base.__dict__, "profile_dir": EXAMPLE_PROFILE,
                      "runs_log_path": config.runs_log_path})
    ws.jd_dir.mkdir()
    return ws


@pytest.fixture
def ids(ws):
    return seed(ws)


@pytest.fixture
def model(monkeypatch):
    state = SimpleNamespace(parsed=[], scored=[], clients=0, company="Acme Logistics")

    def get_client(call_type, config, context):
        state.clients += 1
        return SimpleNamespace(context=context)

    def parse_jd(text, *, client, source):
        state.parsed.append((text, source))
        return JobDescription(title="Engineering Manager", company=state.company,
                              work_type=WorkType.permanent, work_arrangement=WorkArrangement.hybrid,
                              raw_text=text, ingested_at=datetime.now(timezone.utc), source=source)

    def score_fit(jd, profile, *, client):
        state.scored.append(jd.id)
        return FitAssessment(jd_id=jd.id, overall_score=71, recruiter_screen_score=64,
                             verdict=Verdict.apply, rationale="Invented rationale.",
                             target_role_match=True, target_role_note="Invented.",
                             scored_at=datetime.now(timezone.utc))

    monkeypatch.setattr(ads, "get_client", get_client)
    monkeypatch.setattr(scoring, "get_client", get_client)
    monkeypatch.setattr(ads, "parse_jd", parse_jd)
    monkeypatch.setattr(scoring, "score_fit", score_fit)
    return state


@pytest.fixture
def client(ws, config):
    app = create_app(workspace_factory=lambda: ws, config=config, port=PORT, token=TOKEN,
                     runner=SyncRunner(), today=lambda: TODAY)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    return c


def save(ws, name, text=AD, age=0):
    path = ws.jd_dir / name
    path.write_text(text)
    stamp = datetime.now().timestamp() - age
    os.utime(path, (stamp, stamp))
    return path


# -- Scenario 1: the newest saved ad is named, with its cost, before parsing --


def test_newest_saved_ad_is_named_then_confirmed_then_parsed(client, ws, model):
    save(ws, "older-ad.txt", age=600)
    save(ws, "acme-logistics-em.txt")
    assert "acme-logistics-em.txt" in client.get("/ads/new").text

    page = client.post("/ads/new/confirm", data={"csrf": TOKEN, "mode": "latest", "source": "seek"})
    body = flat(page)
    assert "Parse acme-logistics-em.txt?" in body
    assert "Expected cost ~$" in body and "Confirm and parse" in body
    assert model.clients == 0 and model.parsed == []

    response = client.post("/ads/new", data={"csrf": TOKEN, "confirmed": "1", "mode": "saved",
                                             "name": "acme-logistics-em.txt", "source": "seek"})
    assert response.status_code == 303
    landed = client.get(response.headers["location"])
    assert landed.status_code == 303 and re.fullmatch(r"/ads/\d+", landed.headers["location"])
    assert model.parsed == [(AD, "seek")]
    page = flat(client.get(landed.headers["location"]))
    assert "Engineering Manager" in page and "Review cost and score" in page


def test_no_start_without_confirmation(client, ws, model):
    save(ws, "acme.txt")
    response = client.post("/ads/new", data={"csrf": TOKEN, "mode": "saved", "name": "acme.txt"})
    assert response.status_code == 409 and "confirm the cost first" in flat(response)
    assert model.clients == 0 and runs.running(ws) == [] and runs.unseen_finished(ws) == []


# -- Scenario 2: a file of the wrong kind is refused before any cost ----------


def test_unsupported_upload_is_refused_before_anything(client, ws, model):
    response = client.post("/ads/new/confirm", data={"csrf": TOKEN, "mode": "upload"},
                           files={"upload": ("ad.docx", b"PK...", "application/octet-stream")})
    assert response.status_code == 409
    assert "Accepted: .mhtml, .pdf, .txt" in flat(response)
    assert list(ws.jd_dir.iterdir()) == [] and model.clients == 0


def test_upload_is_kept_in_jd_dir_and_confirmed_by_name(client, ws, model):
    response = client.post("/ads/new/confirm", data={"csrf": TOKEN, "mode": "upload"},
                           files={"upload": ("acme.txt", AD.encode(), "text/plain")})
    assert response.status_code == 200 and "Parse acme.txt?" in flat(response)
    assert (ws.jd_dir / "acme.txt").read_text() == AD
    assert 'name="name" value="acme.txt"' in response.text and str(ws.jd_dir) not in re.findall(
        r'value="([^"]*)"', response.text)


def test_same_name_different_content_is_refused(client, ws, model):
    save(ws, "acme.txt", text="the ad that was saved first")
    response = client.post("/ads/new/confirm", data={"csrf": TOKEN, "mode": "upload"},
                           files={"upload": ("acme.txt", AD.encode(), "text/plain")})
    assert response.status_code == 409 and "already holds a different acme.txt" in flat(response)
    assert (ws.jd_dir / "acme.txt").read_text() == "the ad that was saved first"


def test_traversal_names_write_nothing_outside_jd_dir(client, ws, model, tmp_path):
    for evil in ["../escape.txt", "..\\escape.txt", "sub/escape.txt", ".hidden.txt"]:
        response = client.post("/ads/new/confirm", data={"csrf": TOKEN, "mode": "upload"},
                               files={"upload": (evil, AD.encode(), "text/plain")})
        assert response.status_code == 409, evil
    for evil in ["../jobagent.db", "/etc/hosts"]:
        response = client.post("/ads/new", data={"csrf": TOKEN, "confirmed": "1",
                                                 "mode": "saved", "name": evil})
        assert response.status_code == 409, evil
    assert not (tmp_path / "escape.txt").exists() and list(ws.jd_dir.iterdir()) == []
    assert model.clients == 0


def test_truncated_capture_cannot_be_confirmed_or_started(client, ws, model, monkeypatch):
    save(ws, "acme.pdf", text="%PDF stand-in")
    page = ExtractedAd(text="Half an ad", full_text="x" * 4000, source_url=None,
                       page_title=None, posting_metadata=None, truncated=True)
    monkeypatch.setattr(ads, "extract_saved_page", lambda file: page)
    body = flat(client.post("/ads/new/confirm", data={"csrf": TOKEN, "mode": "latest"}))
    assert "this capture is incomplete" in body and "Confirm and parse" not in body
    response = client.post("/ads/new", data={"csrf": TOKEN, "confirmed": "1", "mode": "saved", "name": "acme.pdf"})
    assert response.status_code == 409 and model.clients == 0


# -- Scenario 3: company history once the parse says who it is ----------------


def test_history_is_shown_on_the_new_ad(client, ws, ids, model):
    model.company = "Northwind Freight"
    save(ws, "northwind.txt")
    response = client.post("/ads/new", data={"csrf": TOKEN, "confirmed": "1", "mode": "saved", "name": "northwind.txt"})
    ad_page = client.get(client.get(response.headers["location"]).headers["location"])
    assert "You have seen Northwind Freight before." in flat(ad_page)


# -- pasted text ---------------------------------------------------------------


def test_paste_round_trip_and_double_submit(client, ws, model, monkeypatch):
    body = flat(client.post("/ads/new/confirm", data={"csrf": TOKEN, "mode": "paste", "text": AD}))
    assert "Parse the pasted ad?" in body

    # A run already going for the same text: the second submit joins it.
    key = ads.input_key(ads.read_ad(text=AD.strip()))
    going = runs.start_run(ws, kind="add_ad", jd_id=None, run_id="r", request={"input_key": key})
    response = client.post("/ads/new", data={"csrf": TOKEN, "confirmed": "1", "mode": "paste", "text": AD})
    assert response.headers["location"] == f"/runs/{going}/view" and model.parsed == []

    runs.finish_run(ws, going, status="failed", error="stopped")
    client.post("/ads/new", data={"csrf": TOKEN, "confirmed": "1", "mode": "paste", "text": AD})
    assert len(model.parsed) == 1


# -- scoring ---------------------------------------------------------------------


def test_score_confirm_then_start(client, ws, ids, model):
    body = flat(client.post(f"/ads/{ids['contoso']}/score/confirm", data={"csrf": TOKEN}))
    assert "Score Head of Engineering" in body and "Expected cost ~$" in body
    assert model.clients == 0

    refused = client.post(f"/ads/{ids['contoso']}/score", data={"csrf": TOKEN})
    assert refused.status_code == 409 and model.clients == 0

    response = client.post(f"/ads/{ids['contoso']}/score", data={"csrf": TOKEN, "confirmed": "1"})
    assert response.headers["location"] == f"/ads/{ids['contoso']}"
    assert model.scored == [ids["contoso"]]
    page = flat(client.get(f"/ads/{ids['contoso']}"))
    assert "71/100" in page and "Scoring finished" in page and "Re-score" in page


def test_a_stub_needs_the_force_box(client, ws, model):
    with store.open_store(ws.db_path) as conn:
        stub = store.add_jd(conn, JobDescription(
            title="Digital Lead", company="Contoso Health", work_type=WorkType.permanent,
            work_arrangement=WorkArrangement.hybrid, raw_text="Two sentences. Apply now.",
            ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc)))
    assert "Score it anyway" in flat(client.post(f"/ads/{stub}/score/confirm", data={"csrf": TOKEN}))
    refused = client.post(f"/ads/{stub}/score", data={"csrf": TOKEN, "confirmed": "1"})
    assert refused.status_code == 409 and model.clients == 0
    client.post(f"/ads/{stub}/score", data={"csrf": TOKEN, "confirmed": "1", "force": "1"})
    assert model.scored == [stub]


def test_score_is_logged_as_ui(client, ws, ids, model, monkeypatch):
    seen = []
    real = scoring.score

    def spy(ws_, config, ctx, *a, **k):
        seen.append((ctx.source, ctx.command))
        return real(ws_, config, ctx, *a, **k)

    monkeypatch.setattr(scoring, "score", spy)
    client.post(f"/ads/{ids['contoso']}/score", data={"csrf": TOKEN, "confirmed": "1"})
    assert seen == [("ui", "score")]
