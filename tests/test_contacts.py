"""Contacts and follow-ups (REVIEW-2026-10-18, task 5). Invented people only."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from typer.testing import CliRunner

from jobagent.cli import apply as apply_cli
from jobagent.cli import contacts as contacts_cli
from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import ContactKind
from jobagent.services import contacts
from jobagent.services.contacts import NoSuchContact
from jobagent.services.refusals import BadDate, NoSuchAd
from jobagent.services.workspace import Workspace
from tests.ui_seed import workspace

TODAY = date(2026, 10, 23)
runner = CliRunner()


@pytest.fixture
def ws(tmp_path):
    return workspace(tmp_path)


def test_interval_and_date_forms():
    assert contacts.next_date(None, TODAY) == TODAY + timedelta(weeks=6)
    assert contacts.next_date("10d", TODAY) == TODAY + timedelta(days=10)
    assert contacts.next_date("2W", TODAY) == TODAY + timedelta(weeks=2)
    assert contacts.next_date("1m", TODAY) == TODAY + timedelta(days=30)
    assert contacts.next_date("2026-12-01", TODAY) == date(2026, 12, 1)
    with pytest.raises(BadDate):
        contacts.next_date("soon", TODAY)
    with pytest.raises(BadDate):
        contacts.next_date("2026-01-01", TODAY)


def test_add_sets_the_first_follow_up_from_first_contact(ws):
    c = contacts.add(ws, name="Jo Example", firm="Contoso Talent", first_contact=date(2026, 10, 1),
                     today=TODAY)
    assert c.id and c.last_touch == date(2026, 10, 1)
    assert c.next_followup == date(2026, 10, 1) + timedelta(weeks=6)
    assert c.kind is ContactKind.agency_recruiter


def test_add_refuses_a_future_first_contact_and_an_unknown_ad(ws):
    with pytest.raises(BadDate):
        contacts.add(ws, name="Jo", first_contact=TODAY + timedelta(days=1), today=TODAY)
    with pytest.raises(NoSuchAd):
        contacts.add(ws, name="Jo", jd_id=999, today=TODAY)


def test_touch_moves_the_follow_up_and_appends_a_dated_note(ws):
    c = contacts.add(ws, name="Jo", notes="Places contract .NET.", today=TODAY - timedelta(days=50))
    touched = contacts.touch(ws, c.id, next_followup="3w", note="Called; nothing this month.",
                             today=TODAY)
    assert touched.last_touch == TODAY and touched.next_followup == TODAY + timedelta(weeks=3)
    assert touched.notes == "Places contract .NET.\n2026-10-23: Called; nothing this month."
    assert contacts.list_all(ws)[0].notes == touched.notes
    with pytest.raises(NoSuchContact):
        contacts.touch(ws, 999, today=TODAY)


def test_due_is_overdue_or_within_the_week(ws):
    overdue = contacts.add(ws, name="Overdue", first_contact=TODAY - timedelta(weeks=7), today=TODAY)
    soon = contacts.add(ws, name="Soon", next_followup="5d", today=TODAY)
    contacts.add(ws, name="Later", next_followup="3w", today=TODAY)
    assert [c.id for c in contacts.due(ws, TODAY)] == [overdue.id, soon.id]


def test_a_contact_survives_its_ad_being_deleted(ws):
    from tests.ui_seed import seed

    ids = seed(ws)
    c = contacts.add(ws, name="Jo", today=TODAY)
    contacts.link(ws, c.id, ids["contoso"])
    with store.open_store(ws.db_path) as conn:
        conn.execute("DELETE FROM job_descriptions WHERE id = ?", (ids["contoso"],))
        conn.commit()
    assert contacts.list_all(ws)[0].jd_id is None


def test_cli_add_list_touch_and_status_shows_what_is_due(tmp_path, monkeypatch):
    config = Config(_env_file=None, db_path=tmp_path / "jobagent.db", output_dir=tmp_path / "out")
    monkeypatch.setattr(contacts_cli, "get_config", lambda: config)
    monkeypatch.setattr(apply_cli, "get_config", lambda: config)

    result = runner.invoke(app, ["contact", "add", "Jo Example", "--firm", "Contoso Talent",
                                 "--next", "2d"])
    assert result.exit_code == 0, result.output
    assert "Added contact 1: Jo Example, Contoso Talent" in result.output

    assert "Jo Example" in runner.invoke(app, ["contact", "list"]).output

    status = runner.invoke(app, ["status"])
    assert "Follow-ups due this week" in status.output and "Jo Example" in status.output

    result = runner.invoke(app, ["contact", "touch", "1", "--note", "Sent the CV."])
    assert result.exit_code == 0 and "Next follow-up" in result.output
    assert "Follow-ups due" not in runner.invoke(app, ["status"]).output

    bad = runner.invoke(app, ["contact", "touch", "1", "--next", "whenever"])
    assert bad.exit_code == 2
    missing = runner.invoke(app, ["contact", "touch", "7"])
    assert missing.exit_code == 1 and "No contact with id 7" in missing.output
