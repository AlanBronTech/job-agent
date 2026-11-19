"""services.listing: list rows and the detail view, from invented data."""

from __future__ import annotations

import pytest

from jobagent.core.models import ApplicationStatus, Verdict
from jobagent.services import listing
from jobagent.services.refusals import NoSuchAd
from jobagent.services.workspace import Workspace
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


def test_detail_carries_the_master_choice(ws, ids, tmp_path):
    from tests.ui_seed import masters_profile

    with_masters = Workspace(**{**ws.__dict__, "profile_dir": masters_profile(tmp_path)})
    detail = listing.ad_detail(with_masters, ids["acme"], today=TODAY)
    assert detail.master is not None and detail.master.master.id == "manager"


def test_detail_without_a_profile_has_no_master(ws, ids):
    assert listing.ad_detail(ws, ids["acme"], today=TODAY).master is None


# -- the Jobs page's view ------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from jobagent.core.models import WorkType  # noqa: E402

T = datetime(2026, 9, 1, tzinfo=timezone.utc)


def row(jd_id, *, status=None, score=None, days_ago=0, applied_ago=None, updated_ago=None,
        verdict=None, work=WorkType.permanent, title="Engineering Manager", company="Fabrikam"):
    today = TODAY
    return listing.AdRow(
        jd_id=jd_id, title=title, company=company,
        captured=datetime.combine(today - timedelta(days=days_ago), datetime.min.time(), timezone.utc),
        verdict=verdict, overall_score=score, recruiter_score=score, status=status,
        has_documents=False, stale=False, work_type=work,
        applied_on=today - timedelta(days=applied_ago) if applied_ago is not None else None,
        updated_at=(datetime.combine(today - timedelta(days=updated_ago), datetime.min.time(), timezone.utc)
                    if updated_ago is not None else None),
    )


def view(**kw):
    return listing.JobsView(**{"stage": "all", **kw})


def ids_of(rows):
    return [r.jd_id for r in rows]


S = ApplicationStatus


def test_default_view_is_open_jobs():
    rows = [row(1), row(2, status=S.applied), row(3, status=S.interview_1),
            row(4, status=S.not_applied), row(5, status=S.rejected_screen), row(6, status=S.identified)]
    assert sorted(ids_of(listing.view_rows(rows, listing.JobsView(), TODAY))) == [1, 2, 3, 6]


@pytest.mark.parametrize("stage, expected", [
    ("decide", [1, 6]), ("applied", [2]), ("progress", [3]), ("closed", [4, 5, 7, 8, 9, 10]),
    ("rejected", [5, 7]), ("rejected_screen", [5]), ("rejected_after_interview", [7]),
    ("no_reply", [8, 9]), ("not_applied", [4]), ("withdrew", [10]),
])
def test_stages(stage, expected):
    rows = [row(1), row(2, status=S.applied), row(3, status=S.offer), row(4, status=S.not_applied),
            row(5, status=S.rejected_screen), row(6, status=S.identified),
            row(7, status=S.rejected_after_interview), row(8, status=S.applied_no_reply),
            row(9, status=S.ghosted_after_contact), row(10, status=S.withdrew)]
    got = listing.view_rows(rows, view(stage=stage, sort="oldest"), TODAY)
    assert sorted(ids_of(got)) == expected


def test_follow_up_due_is_applied_over_30_days_ago():
    rows = [row(1, status=S.applied, applied_ago=31), row(2, status=S.applied, applied_ago=10),
            row(3, status=S.applied_no_reply, applied_ago=60), row(4, status=S.applied, updated_ago=40)]
    assert sorted(ids_of(listing.view_rows(rows, view(stage="followup"), TODAY))) == [1, 4]


def test_sorts():
    rows = [row(1, score=50, days_ago=5, updated_ago=0), row(2, score=80, days_ago=1),
            row(3, days_ago=3), row(4, score=20, days_ago=9)]
    order = lambda s: ids_of(listing.view_rows(rows, view(sort=s), TODAY))  # noqa: E731
    assert order("date") == [2, 3, 1, 4]
    assert order("oldest") == [4, 1, 3, 2]
    assert order("score") == [2, 1, 4, 3]
    assert order("score_low") == [4, 1, 2, 3]
    assert order("activity")[0] == 1


def test_days_verdict_work_and_search_combine():
    rows = [row(1, days_ago=3, verdict=Verdict.apply, work=WorkType.contract, company="Contoso"),
            row(2, days_ago=40, verdict=Verdict.apply, work=WorkType.contract),
            row(3, days_ago=3, verdict=Verdict.skip, work=WorkType.fixed_term),
            row(4, days_ago=3, work=WorkType.permanent)]
    pick = lambda **kw: sorted(ids_of(listing.view_rows(rows, view(**kw), TODAY)))  # noqa: E731
    assert pick(days=30) == [1, 3, 4]
    assert pick(verdict="apply") == [1, 2]
    assert pick(verdict="unscored") == [4]
    assert pick(work="contract") == [1, 2, 3]
    assert pick(work="permanent") == [4]
    assert pick(q="contoso") == [1]
    assert pick(days=30, work="contract", verdict="apply") == [1]


def test_counts_are_per_stage_before_other_filters():
    rows = [row(1), row(2, status=S.not_applied), row(3, status=S.rejected_screen)]
    counts = listing.stage_counts(rows, TODAY)
    assert (counts["open"], counts["closed"], counts["rejected"], counts["all"]) == (1, 2, 1, 3)


def test_unknown_params_fall_back():
    v = listing.JobsView.from_params({"stage": "x", "sort": "y", "days": "12", "verdict": "z", "work": "w"})
    assert v == listing.JobsView()
    assert listing.JobsView.from_params({"days": "30", "q": "  acme "}) == listing.JobsView(days=30, q="acme")
