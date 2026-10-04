"""services.pipeline: the same record the CLI writes, notes appended."""

from __future__ import annotations

from datetime import date

import pytest

from jobagent.core import store
from jobagent.core.models import ApplicationStatus, Worth
from jobagent.services import pipeline
from jobagent.services.refusals import NoSuchAd
from tests.ui_seed import seed, workspace


@pytest.fixture
def ws(tmp_path):
    return workspace(tmp_path)


@pytest.fixture
def ids(ws):
    return seed(ws)


def test_outcome_creates_then_appends(ws, ids):
    pipeline.outcome(ws, ids["contoso"], ApplicationStatus.not_applied, note="first")
    _, app = pipeline.outcome(ws, ids["contoso"], ApplicationStatus.not_applied,
                              worth=Worth.no, why="Wrong shape", note="second")
    assert app.status is ApplicationStatus.not_applied
    assert app.notes == "first\nsecond"
    assert (app.worth_applying, app.worth_why, app.worth_derived) == (Worth.no, "Wrong shape", False)
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["contoso"]).notes == "first\nsecond"


def test_save_sets_applied_fields(ws, ids):
    _, app = pipeline.save(ws, ids["acme"], status=ApplicationStatus.applied,
                           applied_on=date(2026, 10, 4), channel="linkedin")
    assert (app.applied_on, app.channel) == (date(2026, 10, 4), "linkedin")


def test_missing_ad(ws, ids):
    with pytest.raises(NoSuchAd):
        pipeline.outcome(ws, 999, ApplicationStatus.not_applied)
