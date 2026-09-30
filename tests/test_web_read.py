"""User Story 1: read the shortlist and an assessment. Free, read-only, invented data.

Every test here runs with the model client booby-trapped: reading must never
build one.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from jobagent.adapters import llm
from jobagent.adapters.document_store import LocalFolderStore
from jobagent.core import store
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from tests.ui_seed import TODAY, jd, seed

PORT = 8765
TOKEN = "test-token"


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, args, check):
        self.calls.append(args)


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a read-only page built a model client")

    monkeypatch.setattr(llm, "get_client", refuse)


@pytest.fixture
def run():
    return FakeRun()


@pytest.fixture
def ws(tmp_path, run):
    # No API key and no profile: reading must not need either.
    return Workspace(
        owner="local",
        profile_dir=None,
        db_path=tmp_path / "jobagent.db",
        runs_log_path=tmp_path / "runs.jsonl",
        jd_dir=tmp_path / "jds",
        documents=LocalFolderStore(tmp_path / "out", run=run),
    )


@pytest.fixture
def ids(ws):
    return seed(ws)


@pytest.fixture
def client(ws):
    app = create_app(
        workspace_factory=lambda: ws,
        config=None,
        port=PORT,
        token=TOKEN,
        today=lambda: TODAY,
    )
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.get(f"/?t={TOKEN}")
    return c


def text(response) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.text))


# -- Scenario 1: one row per ad, newest first ---------------------------------


def test_list_shows_every_ad_newest_first(client, ids):
    page = client.get("/")
    assert page.status_code == 200
    order = [int(m) for m in re.findall(r'href="/ads/(\d+)"', page.text)]
    assert order == [ids["contoso"], ids["fabrikam"], ids["acme"], ids["northwind"], ids["northwind_old"]]
    body = text(page)
    assert "78 / 70" in body and "41 / 35" in body
    assert "rejected screen" in body and "not scored" in body and "stale" in body


def test_list_by_score(client, ids):
    order = [int(m) for m in re.findall(r'href="/ads/(\d+)"', client.get("/?sort=score").text)]
    assert order[:3] == [ids["acme"], ids["fabrikam"], ids["northwind"]]


def test_empty_store(client):
    assert "No ads yet" in client.get("/").text


# -- Scenario 2: a breach overrides; "not stated" is never met ----------------


def test_breach_is_shown_as_overriding_the_verdict(client, ids):
    body = text(client.get(f"/ads/{ids['northwind']}"))
    assert "Hard filter breached — skip, whatever the score." in body
    assert "salary floor" in body


def test_unknown_constraint_reads_not_stated(client, ids):
    page = client.get(f"/ads/{ids['acme']}")
    items = page.text.split("<li>")
    office = next(i for i in items if "office location" in i)
    employment = next(i for i in items if "employment type" in i)
    assert 'class="mark unknown"' in office and 'class="mark ok"' not in office
    assert 'class="mark ok"' in employment
    assert "not stated" in text(page)


# -- Scenario 3: history is information, the verdict is unchanged -------------


def test_prior_rejection_is_shown_and_verdict_unchanged(client, ids):
    body = text(client.get(f"/ads/{ids['northwind']}"))
    assert "You have seen Northwind Freight before." in body
    assert "does not change the verdict" in body
    assert "rejected screen" in body
    assert "skip" in body  # the stored verdict, as scored


# -- Scenario 4: an amendment after scoring is flagged ------------------------


def test_amended_ad_is_flagged_stale(client, ids):
    assert "predates an amendment" in text(client.get(f"/ads/{ids['fabrikam']}"))
    assert "predates an amendment" not in text(client.get(f"/ads/{ids['acme']}"))


def test_missing_ad_is_404(client, ids):
    assert client.get("/ads/999").status_code == 404


# -- FR-008: nothing links off-host --------------------------------------------


def test_no_link_leaves_the_machine(client, ids):
    for path in ["/", *(f"/ads/{i}" for i in ids.values())]:
        page = client.get(path).text
        for href in re.findall(r'href="([^"]+)"', page):
            assert href.startswith("/"), (path, href)
        for src in re.findall(r'src="([^"]+)"', page):
            assert src.startswith("/"), (path, src)
    # The ad's own URL is shown, as text.
    assert "https://jobs.example.invalid/acme-em" in client.get(f"/ads/{ids['acme']}").text


# -- Documents: open and reveal, only what is listed --------------------------


def seed_documents(ws, ids):
    with store.open_store(ws.db_path) as conn:
        acme = store.get_jd(conn, ids["acme"])
    path = ws.documents.path_for_write(acme, TODAY, "AlanBron_Resume_AcmeLogistics_202609.docx")
    path.write_bytes(b"docx")
    return path


def test_documents_listed_with_open_and_reveal(client, ws, ids):
    path = seed_documents(ws, ids)
    page = client.get(f"/ads/{ids['acme']}").text
    assert path.name in page and path.parent.name in page
    assert "Reveal in Finder" in page and ">Open<" in page
    assert "documents generated, not recorded as applied" in page


def test_open_and_reveal(client, ws, ids, run):
    path = seed_documents(ws, ids)
    folder = path.parent.name
    opened = client.post(
        f"/ads/{ids['acme']}/documents/open",
        data={"csrf": TOKEN, "folder": folder, "name": path.name},
    )
    revealed = client.post(
        f"/ads/{ids['acme']}/documents/reveal", data={"csrf": TOKEN, "folder": folder}
    )
    assert (opened.status_code, revealed.status_code) == (204, 204)
    assert run.calls == [
        ["open", str(path.resolve())],
        ["open", "-R", str(path.parent.resolve())],
    ]


def test_forged_open_requests_are_refused(client, ws, ids, run):
    path = seed_documents(ws, ids)
    folder = path.parent.name
    attempts = [
        (ids["northwind"], folder, path.name),  # another ad's folder
        (ids["acme"], "../..", "etc"),
        (ids["acme"], folder, "../../../../etc/hosts"),
        (999, folder, path.name),
    ]
    for jd_id, f, name in attempts:
        response = client.post(
            f"/ads/{jd_id}/documents/open", data={"csrf": TOKEN, "folder": f, "name": name}
        )
        assert response.status_code == 404, (jd_id, f, name)
    assert client.post(
        f"/ads/{ids['acme']}/documents/open", data={"folder": folder, "name": path.name}
    ).status_code == 403
    assert run.calls == []


# -- SC-002: under a second with 100 ads --------------------------------------


def test_hundred_ads_render_quickly(client, ws):
    with store.open_store(ws.db_path) as conn:
        for n in range(100):
            ad = jd(f"Role {n}", f"Invented Co {n}", 0)
            ad.ingested_at = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(hours=n)
            store.add_jd(conn, ad)
    for path in ["/", "/?sort=score", "/ads/50"]:
        started = time.perf_counter()
        assert client.get(path).status_code == 200
        assert time.perf_counter() - started < 1.0, path
