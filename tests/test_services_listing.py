"""services.listing: list rows and the detail view, from invented data."""

from __future__ import annotations

import pytest

from jobagent.core.models import ApplicationStatus, Verdict
from jobagent.services import listing
from jobagent.services.refusals import NoSuchAd
from tests.ui_seed import TODAY, seed, workspace


@pytest.fixture
def ws(tmp_path):
    return workspace(tmp_path)


@pytest.fixture
def ids(ws):
    return seed(ws)


def test_rows_newest_first(ws, ids):
    rows = listing.ad_rows(ws, today=TODAY)
    assert [r.company for r in rows] == [
        "Contoso Health",
        "Fabrikam Energy",
        "Acme Logistics",
        "Northwind Freight",
        "Northwind Freight",
    ]


def test_rows_by_score_put_unscored_last(ws, ids):
    rows = listing.ad_rows(ws, today=TODAY, sort="score")
    assert [r.overall_score for r in rows] == [78, 60, 41, None, None]


def test_row_fields(ws, ids):
    by_id = {r.jd_id: r for r in listing.ad_rows(ws, today=TODAY)}
    acme = by_id[ids["acme"]]
    assert (acme.verdict, acme.overall_score, acme.recruiter_score) == (Verdict.apply, 78, 70)
    assert by_id[ids["northwind_old"]].status is ApplicationStatus.rejected_screen
    assert by_id[ids["contoso"]].verdict is None
    assert by_id[ids["fabrikam"]].stale
    assert not acme.stale and not acme.has_documents


def test_row_sees_documents_on_disk(ws, ids):
    detail = listing.ad_detail(ws, ids["acme"], today=TODAY)
    ws.documents.path_for_write(detail.jd, TODAY, "r.docx").write_bytes(b"x")
    by_id = {r.jd_id: r for r in listing.ad_rows(ws, today=TODAY)}
    assert by_id[ids["acme"]].has_documents


def test_detail(ws, ids):
    detail = listing.ad_detail(ws, ids["northwind"], today=TODAY)
    assert detail.assessment.verdict is Verdict.skip
    assert [e.jd_id for e in detail.history.encounters] == [ids["northwind_old"]]
    assert detail.application is None
    assert not detail.stale


def test_detail_stale_after_amendment(ws, ids):
    assert listing.ad_detail(ws, ids["fabrikam"], today=TODAY).stale


def test_unscored_detail_is_not_stale(ws, ids):
    detail = listing.ad_detail(ws, ids["contoso"], today=TODAY)
    assert detail.assessment is None and not detail.stale


def test_missing_ad(ws, ids):
    with pytest.raises(NoSuchAd):
        listing.ad_detail(ws, 999, today=TODAY)
