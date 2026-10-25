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
    assert 'value="rejected_screen" selected' in page.text
    assert "not scored" in body and "stale" in body


def test_list_by_score(client, ids):
    order = [int(m) for m in re.findall(r'href="/ads/(\d+)"', client.get("/?sort=score").text)]
    assert order[:3] == [ids["acme"], ids["fabrikam"], ids["northwind"]]


def test_empty_store(client):
    assert "No jobs yet" in client.get("/").text


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


def test_no_link_leaves_the_machine_except_the_ads_own(client, ids):
    """FR-008, amended 2026-10-25: the one link off the machine is the ad's own
    page, so Alan can apply on it. Nothing is fetched or embedded."""
    for path in ["/", *(f"/ads/{i}" for i in ids.values())]:
        page = client.get(path).text
        for href in re.findall(r'href="([^"]+)"', page):
            assert href.startswith("/") or href == "https://jobs.example.invalid/acme-em", (path, href)
        for src in re.findall(r'src="([^"]+)"', page):
            assert src.startswith("/"), (path, src)
    page = client.get(f"/ads/{ids['acme']}").text
    assert 'href="https://jobs.example.invalid/acme-em" target="_blank" rel="noopener noreferrer" data-window' in page


def test_a_source_that_is_not_a_web_address_is_never_a_link(client, ws, ids):
    with store.open_store(ws.db_path) as conn:
        conn.execute("UPDATE job_descriptions SET source_url = 'javascript:alert(1)' WHERE id = ?", (ids["acme"],))
        conn.commit()
    page = client.get(f"/ads/{ids['acme']}").text
    assert 'href="javascript' not in page and "javascript:alert(1)" in page


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


# -- recording where an application stands, from its page -------------------------


def test_the_pipeline_form_records_applied_with_todays_date(client, ws, ids):
    page = client.get(f"/ads/{ids['contoso']}").text
    assert 'name="status"' in page and "Applied, no reply" in page and "careers site" in page
    saved = client.post(f"/ads/{ids['contoso']}/pipeline", data={
        "csrf": TOKEN, "status": "applied", "channel": "recruiter", "channel_detail": "Jane Smith",
        "note": "Sent the v2 resume."})
    assert saved.status_code == 303
    with store.open_store(ws.db_path) as conn:
        app = store.get_application(conn, ids["contoso"])
    assert app.status.value == "applied" and app.applied_on == TODAY
    assert app.channel == "recruiter — Jane Smith" and app.notes == "Sent the v2 resume."
    assert "Saved." in client.get(f"/ads/{ids['contoso']}?saved=1").text


def test_the_pipeline_form_moves_an_outcome_and_keeps_what_is_not_changed(client, ws, ids):
    client.post(f"/ads/{ids['contoso']}/pipeline", data={"csrf": TOKEN, "status": "applied",
                                                          "channel": "seek", "applied_on": "2026-09-20"})
    client.post(f"/ads/{ids['contoso']}/pipeline", data={"csrf": TOKEN, "status": "interview_1",
                                                          "worth": "yes", "why": "Got a call."})
    with store.open_store(ws.db_path) as conn:
        app = store.get_application(conn, ids["contoso"])
    assert (app.status.value, app.channel, str(app.applied_on)) == ("interview_1", "seek", "2026-09-20")
    assert app.worth_applying.value == "yes" and app.worth_why == "Got a call."


def test_a_bad_status_or_token_changes_nothing(client, ws, ids):
    assert client.post(f"/ads/{ids['contoso']}/pipeline",
                       data={"csrf": TOKEN, "status": "hired"}).status_code == 409
    assert client.post(f"/ads/{ids['contoso']}/pipeline",
                       data={"csrf": "wrong", "status": "applied"}).status_code in (400, 403)
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["contoso"]) is None


# -- REVIEW-2026-10-16 D9: status is never set implicitly ---------------------------


def test_the_status_has_no_default_and_saving_without_one_records_nothing(client, ws, ids):
    page = client.get(f"/ads/{ids['contoso']}").text
    form = page.split('name="status"')[1].split("</select>")[0]
    assert 'value="" selected' in form and 'value="applied" selected' not in form
    response = client.post(f"/ads/{ids['contoso']}/pipeline",
                           data={"csrf": TOKEN, "status": "", "note": "Just a note."})
    assert response.status_code == 409 and "Choose a status" in response.text
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["contoso"]) is None


def test_applied_with_a_not_ready_document_needs_an_explicit_confirmation(client, ws, ids):
    with store.open_store(ws.db_path) as conn:
        jd_row = store.get_jd(conn, ids["contoso"])
    folder = ws.documents.path_for_write(jd_row, TODAY, "x").parent
    (folder / "AlanBron_CoverLetter_ContosoHealth_202609_NOT-READY.docx").write_bytes(b"x")
    refused = client.post(f"/ads/{ids['contoso']}/pipeline", data={"csrf": TOKEN, "status": "applied"})
    assert refused.status_code == 409 and "NOT-READY" in refused.text and 'name="confirm_blockers"' in refused.text
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["contoso"]) is None
    ok = client.post(f"/ads/{ids['contoso']}/pipeline",
                     data={"csrf": TOKEN, "status": "applied", "confirm_blockers": "1"})
    assert ok.status_code == 303


# -- The Jobs page: the status changed in place -------------------------------------


def test_the_jobs_page_changes_a_status_in_the_row(client, ws, ids):
    page = client.get("/").text
    assert f'hx-post="/ads/{ids["contoso"]}/status"' in page and "Chose not to apply" in page
    cell = client.post(f"/ads/{ids['contoso']}/status", data={"csrf": TOKEN, "status": "not_applied"})
    assert cell.status_code == 200 and 'value="not_applied" selected' in cell.text and "saved" in cell.text
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["contoso"]).status.value == "not_applied"


def test_the_jobs_page_status_keeps_the_pipeline_guards(client, ws, ids):
    assert client.post(f"/ads/{ids['contoso']}/status",
                       data={"csrf": "wrong", "status": "applied"}).status_code in (400, 403)
    with store.open_store(ws.db_path) as conn:
        jd_row = store.get_jd(conn, ids["contoso"])
    folder = ws.documents.path_for_write(jd_row, TODAY, "x").parent
    (folder / "AlanBron_CoverLetter_ContosoHealth_202609_NOT-READY.docx").write_bytes(b"x")
    cell = client.post(f"/ads/{ids['contoso']}/status", data={"csrf": TOKEN, "status": "applied"})
    assert "NOT-READY" in cell.text and f'href="/ads/{ids["contoso"]}#pipeline"' in cell.text
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["contoso"]) is None
