"""The six-month rule in the UI: the flag, the buttons, no Confirm until resolved."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import ApplicationStatus, OutsideApplication, Verdict
from jobagent.services import scoring
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from jobagent.web.runner import SyncRunner
from tests.ui_seed import TODAY, assessment, jd, workspace

PORT = 8765
TOKEN = "test-token"
EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


def flat(response) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", response.text).split())


@pytest.fixture
def ws(tmp_path):
    base = workspace(tmp_path)
    return Workspace(**{**base.__dict__, "profile_dir": EXAMPLE_PROFILE})


@pytest.fixture
def client(ws, monkeypatch):
    def no_client(*a, **k):
        raise AssertionError("reached the model")
    monkeypatch.setattr(scoring, "get_client", no_client)
    config = Config(_env_file=None, db_path=ws.db_path, llm_default="anthropic:claude-sonnet-5",
                    anthropic_api_key="test-key")
    app = create_app(workspace_factory=lambda: ws, config=config, port=PORT, token=TOKEN,
                     runner=SyncRunner(), today=lambda: TODAY)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    return c


@pytest.fixture
def jd_id(ws):
    with store.open_store(ws.db_path) as conn:
        store.add_outside(conn, OutsideApplication(
            company="Fabrikam Medical", title="Engineering Manager", requisition_id="JR_000123",
            applied_on=TODAY - timedelta(days=120), status=ApplicationStatus.applied_no_reply,
            created_at=NOW))
        jd_id = store.add_jd(conn, jd("Engineering Manager", "Fabrikam Medical", 20))
        store.add_assessment(conn, assessment(jd_id, Verdict.apply, 70, 60))
    return jd_id


def test_the_ad_page_shows_the_question_with_buttons(client, jd_id):
    page = client.get(f"/ads/{jd_id}")
    body = flat(page)
    assert "Possibly the same job as your application of" in body and "120 days ago" in body
    assert ">Same job<" in page.text and ">Different job<" in page.text and "Overrule" in page.text


def test_confirm_pages_offer_no_confirm_until_answered(client, jd_id):
    score_page = flat(client.post(f"/ads/{jd_id}/score/confirm", data={"csrf": TOKEN}))
    assert "Answer the question above before scoring" in score_page and "Confirm and score" not in score_page
    gen_page = flat(client.post(f"/ads/{jd_id}/generate/confirm", data={"csrf": TOKEN, "resume": "1"}))
    assert "Answer the question above before generating" in gen_page and "Confirm and generate" not in gen_page


def test_a_forced_start_is_refused_and_spends_nothing(client, jd_id):
    response = client.post(f"/ads/{jd_id}/score", data={"csrf": TOKEN, "confirmed": "1"})
    assert response.status_code == 409 and "applied for recently" in flat(response)


def test_answering_same_makes_it_a_same_job_refusal(client, jd_id):
    response = client.post(f"/ads/{jd_id}/reapply", data={"csrf": TOKEN, "decision": "same"})
    assert response.status_code == 303 and response.headers["location"] == f"/ads/{jd_id}"
    assert "Same job you applied for on" in flat(client.get(f"/ads/{jd_id}"))


def test_answering_different_clears_it(client, jd_id):
    client.post(f"/ads/{jd_id}/reapply", data={"csrf": TOKEN, "decision": "different"})
    page = flat(client.get(f"/ads/{jd_id}"))
    assert "Possibly the same job" not in page and "you said this is a different job" in page
    assert "Confirm and score" in flat(client.post(f"/ads/{jd_id}/score/confirm", data={"csrf": TOKEN}))


def test_overrule(client, jd_id):
    client.post(f"/ads/{jd_id}/reapply", data={"csrf": TOKEN, "decision": "overrule"})
    assert "overruled for this ad" in flat(client.get(f"/ads/{jd_id}"))


def test_decisions_need_the_token_and_a_known_value(client, jd_id):
    assert client.post(f"/ads/{jd_id}/reapply", data={"decision": "same"}).status_code == 403
    assert client.post(f"/ads/{jd_id}/reapply", data={"csrf": TOKEN, "decision": "maybe"}).status_code == 400
    bad = client.post(f"/ads/{jd_id}/reapply", data={"csrf": TOKEN, "decision": "same", "next": "//evil.example"})
    assert bad.headers["location"] == f"/ads/{jd_id}"
