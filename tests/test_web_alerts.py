"""The Alerts page: list, decide, check email. Invented data; no mailbox reached."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from jobagent.adapters import mailbox
from jobagent.config import Config
from jobagent.services import alerts
from jobagent.web.app import create_app
from tests.test_alerts import RULES, SEEK_TEXT
from tests.ui_seed import workspace

PORT, TOKEN = 8765, "test-token"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts, "_rules", lambda w: RULES)
    monkeypatch.setattr(alerts, "_filters", lambda w: (150_000, 800))
    return workspace(tmp_path)


@pytest.fixture
def client(ws):
    app = create_app(workspace_factory=lambda: ws, config=Config(_env_file=None), port=PORT,
                     token=TOKEN, today=lambda: datetime.now(timezone.utc).date())
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    return c


def seed(ws):
    now = datetime.now(timezone.utc)
    alerts.ingest(ws, [mailbox.Mail("m1", "jobmail@s.seek.com.au", "5 new jobs", now, SEEK_TEXT)], now=now)


def test_the_page_lists_suggestions_with_their_links(ws, client):
    seed(ws)
    page = client.get("/alerts").text
    assert "Engineering Manager, Payments Platform" in page
    assert 'href="https://au.seek.com/job/90000001"' in page
    assert "Network Engineering Manager" not in page
    skipped = client.get("/alerts?show=skipped").text
    assert "Network Engineering Manager" in skipped and "title: network" in skipped


def test_a_decision_takes_it_off_the_list(ws, client):
    seed(ws)
    first = alerts.pending(ws, datetime.now(timezone.utc))[0].listing
    response = client.post(f"/alerts/{first.id}/decide",
                           data={"csrf": TOKEN, "decision": "not_qualified", "note": "needs Go"})
    assert response.status_code == 303
    assert first.title not in client.get("/alerts").text.split("Show:")[1]
    decided = client.get("/alerts?show=decided").text
    assert "not qualified" in decided and "needs Go" in decided
    assert client.post(f"/alerts/{first.id}/decide", data={"csrf": "wrong", "decision": "saved"}).status_code == 403


def test_check_email_without_a_mailbox_says_what_to_set(client):
    response = client.post("/alerts/fetch", data={"csrf": TOKEN})
    assert response.status_code == 303 and "GMAIL_ADDRESS" in response.headers["location"].replace("%20", " ")


def test_the_nav_and_the_jobs_page_say_how_many_wait(ws, client):
    assert "from your alert emails" not in client.get("/").text
    seed(ws)
    n = alerts.pending_count(ws, datetime.now(timezone.utc))
    jobs = client.get("/").text
    assert f"{n} jobs from your alert emails to look at" in jobs
    assert f'title="Jobs from your alert emails to look at">{n}</span>' in client.get("/settings").text
    assert "Last checked" in client.get("/alerts").text


def test_job_links_open_in_their_own_window(ws, client):
    seed(ws)
    page = client.get("/alerts").text
    assert 'href="https://au.seek.com/job/90000001" target="_blank" rel="noopener noreferrer" data-window' in page
    assert '/static/window.js' in page
    assert "window.open" in client.get("/static/window.js").text
