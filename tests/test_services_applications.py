"""Outside applications: record, history, the rule, linking. Invented data.

US3 scenarios:
1. recorded with a requisition number → in the company's history
2. without a number → history, and "possibly the same job" for a matching ad
3. linked to an ad added later → one pipeline record keeping the original date
4. a future date → refused
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.cli import outside as outside_cli
from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core import history, store
from jobagent.core.models import ApplicationStatus
from jobagent.services import applications, reapply
from jobagent.services.applications import NoSuchOutside
from jobagent.services.refusals import BadDate, NoSuchAd
from jobagent.services.workspace import Workspace
from tests.ui_seed import jd, workspace

EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
TODAY = date.today()
runner = CliRunner()


@pytest.fixture
def ws(tmp_path):
    base = workspace(tmp_path)
    return Workspace(**{**base.__dict__, "profile_dir": EXAMPLE_PROFILE})


def add_ad(ws, *, req=None, title="Engineering Manager", company="Fabrikam Medical"):
    with store.open_store(ws.db_path) as conn:
        ad = jd(title, company, 30)
        ad.requisition_id = req
        return store.add_jd(conn, ad)


def record(ws, days_ago=90, req="JR_000123", **kw):
    return applications.record_outside(
        ws, company="Fabrikam Medical", title="Engineering Manager",
        applied_on=TODAY - timedelta(days=days_ago), requisition_id=req,
        status=ApplicationStatus.applied_no_reply, **kw)


def company_history(ws, jd_id):
    with store.open_store(ws.db_path) as conn:
        return history.company_history(conn, store.get_jd(conn, jd_id))


def test_1_recorded_and_in_the_company_history(ws):
    r = record(ws)
    jd_id = add_ad(ws, req="JR_000456")  # a different job at the same company
    encounters = company_history(ws, jd_id).encounters
    assert [e.label for e in encounters] == [f"outside {r.id}"]
    assert encounters[0].applied and encounters[0].status is ApplicationStatus.applied_no_reply
    assert reapply.check(ws, jd_id, TODAY).kind == "clear"  # different numbers: different job


def test_2_without_a_number_a_matching_ad_is_possibly_the_same(ws):
    record(ws, req=None)
    jd_id = add_ad(ws)
    assert reapply.check(ws, jd_id, TODAY).kind == "possibly_same"


def test_requisition_match_is_the_same_job(ws):
    record(ws, req="JR_000123")
    jd_id = add_ad(ws, req="JR-000123")
    state = reapply.check(ws, jd_id, TODAY)
    assert state.kind == "same" and state.match.against.startswith("outside:")


def test_3_link_gives_one_record_with_the_original_date(ws):
    r = record(ws, days_ago=150, notes="Receipt only.")
    jd_id = add_ad(ws)
    application = applications.link_outside(ws, r.id, jd_id)
    assert application.applied_on == r.applied_on
    assert application.status is ApplicationStatus.applied_no_reply
    assert "Linked from outside application" in application.notes and "Receipt only." in application.notes
    with store.open_store(ws.db_path) as conn:
        assert store.get_outside(conn, r.id).linked_jd_id == jd_id
        assert store.get_jd(conn, jd_id).requisition_id == "JR_000123"  # copied onto the ad
    # Not counted twice: the history of a third ad shows the linked ad once, no outside row.
    third = add_ad(ws, title="Platform Lead")
    labels = [e.label for e in company_history(ws, third).encounters]
    assert labels.count(f"JD {jd_id}") == 1 and not any(l.startswith("outside") for l in labels)


def test_linking_never_matches_the_ad_to_itself(ws):
    r = record(ws, req="JR_000123")
    jd_id = add_ad(ws, req="JR_000123")
    applications.link_outside(ws, r.id, jd_id)
    assert reapply.check(ws, jd_id, TODAY).kind == "clear"


def test_4_a_future_date_is_refused(ws):
    with pytest.raises(BadDate):
        record(ws, days_ago=-1)
    assert applications.list_outside(ws) == []


def test_link_errors(ws):
    r = record(ws)
    with pytest.raises(NoSuchAd):
        applications.link_outside(ws, r.id, 999)
    with pytest.raises(NoSuchOutside):
        applications.link_outside(ws, 999, add_ad(ws))


# -- CLI ------------------------------------------------------------------------


@pytest.fixture
def cli(ws, monkeypatch):
    cfg = Config(_env_file=None, db_path=ws.db_path, profile_dir=EXAMPLE_PROFILE)
    monkeypatch.setattr(outside_cli, "get_config", lambda: cfg)
    return cfg


def test_cli_add_list_link(ws, cli):
    on = (TODAY - timedelta(days=100)).isoformat()
    added = runner.invoke(app, ["outside", "add", "--company", "Fabrikam Medical",
                                "--title", "Engineering Manager", "--on", on, "--req", "JR_000123",
                                "--status", "applied_no_reply"])
    assert added.exit_code == 0, added.output
    assert "Recorded outside application 1" in added.output and "JR_000123" in added.output
    listed = runner.invoke(app, ["outside", "list"])
    assert "Fabrikam" in listed.output and "Medical" in listed.output and "JR_000123" in listed.output
    jd_id = add_ad(ws)
    linked = runner.invoke(app, ["outside", "link", "1", str(jd_id)])
    assert linked.exit_code == 0 and f"JD {jd_id} now records the application" in linked.output


def test_cli_refuses_a_future_date_and_a_bad_date(ws, cli):
    future = (TODAY + timedelta(days=3)).isoformat()
    assert runner.invoke(app, ["outside", "add", "--company", "X", "--title", "Y", "--on", future]).exit_code == 2
    assert runner.invoke(app, ["outside", "add", "--company", "X", "--title", "Y", "--on", "May 5"]).exit_code == 2


def test_cli_list_when_empty(ws, cli):
    assert "None recorded" in runner.invoke(app, ["outside", "list"]).output
