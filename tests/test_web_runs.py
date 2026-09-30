"""Runs outlive their page: the banner, the polled fragment, seen and interrupted."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobagent.services import runs
from jobagent.web.app import create_app
from jobagent.web.runner import SyncRunner
from tests.ui_seed import TODAY, seed, workspace

PORT = 8765
TOKEN = "test-token"


@pytest.fixture
def ws(tmp_path):
    return workspace(tmp_path)


@pytest.fixture
def ids(ws):
    return seed(ws)


@pytest.fixture
def client(ws):
    app = create_app(workspace_factory=lambda: ws, config=None, port=PORT, token=TOKEN,
                     runner=SyncRunner(), today=lambda: TODAY)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    return c


def finished(ws, jd_id, status="succeeded", title="Engineering Manager", error=None):
    run = runs.start_run(ws, kind="score", jd_id=jd_id, run_id="r", request={"title": title})
    runs.finish_run(ws, run, status=status, error=error)
    return run


def test_a_finished_run_is_announced_on_every_page(client, ws, ids):
    finished(ws, ids["acme"])
    for path in ["/", f"/ads/{ids['contoso']}"]:
        assert "Scoring for Engineering Manager" in client.get(path).text


def test_opening_the_ad_marks_its_runs_seen(client, ws, ids):
    finished(ws, ids["acme"])
    page = " ".join(client.get(f"/ads/{ids['acme']}").text.split())
    assert "Scoring finished" in page  # the outcome, on the ad's own page
    assert "Scoring for" not in client.get("/").text  # and gone from the banner


def test_dismiss_marks_seen_and_goes_back(client, ws, ids):
    run = finished(ws, ids["acme"])
    response = client.post(f"/runs/{run}/seen", data={"csrf": TOKEN, "next": "/?sort=score"})
    assert response.status_code == 303 and response.headers["location"] == "/?sort=score"
    assert runs.unseen_finished(ws) == []


def test_dismiss_never_redirects_off_site(client, ws, ids):
    run = finished(ws, ids["acme"])
    for bad in ["https://evil.example/", "//evil.example/"]:
        response = client.post(f"/runs/{run}/seen", data={"csrf": TOKEN, "next": bad})
        assert response.headers["location"] == "/"


def test_failed_run_shows_its_error(client, ws, ids):
    finished(ws, ids["acme"], status="failed", error="Read timed out.")
    body = client.get("/").text
    assert "failed." in body and "Read timed out." in body


def test_interrupted_run_says_its_cost_may_be_missing(client, ws, ids):
    runs.start_run(ws, kind="prep", jd_id=ids["acme"], run_id="r", request={"title": "EM"})
    runs.interrupt_running(ws)
    body = client.get("/").text
    assert "interrupted when the UI stopped" in body and "may be missing" in body


def test_running_fragment_polls_and_finished_one_refreshes(client, ws, ids):
    run = runs.start_run(ws, kind="prep", jd_id=ids["acme"], run_id="r", request={})
    page = client.get(f"/ads/{ids['acme']}").text
    assert 'hx-get="/runs/%d"' % run in page and "every 2s" in page
    poll = client.get(f"/runs/{run}", headers={"HX-Request": "true"})
    assert "every 2s" in poll.text and "HX-Refresh" not in poll.headers
    runs.finish_run(ws, run, status="succeeded")
    poll = client.get(f"/runs/{run}", headers={"HX-Request": "true"})
    assert poll.headers.get("HX-Refresh") == "true" and "every 2s" not in poll.text


def test_unknown_run_is_404(client):
    assert client.get("/runs/999").status_code == 404
