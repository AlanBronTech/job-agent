"""core.reapply.match: same job, possibly the same job, or a different one.

Invented company (Fabrikam Medical) and requisition numbers throughout.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from jobagent.core.models import Application, ApplicationStatus, OutsideApplication
from jobagent.core.reapply import match, normalise_title
from tests.ui_seed import jd as make_jd

TODAY = date(2026, 10, 4)
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def ad(jd_id, title="Engineering Manager", company="Fabrikam Medical", req=None, url=None):
    a = make_jd(title, company, 1)
    a.id, a.requisition_id, a.source_url = jd_id, req, url
    return a


def applied(jd_id, on, status=ApplicationStatus.applied_no_reply):
    return Application(jd_id=jd_id, status=status, applied_on=on, updated_at=NOW)


def outside(oid, on, req=None, title="Engineering Manager", company="Fabrikam Medical", linked=None):
    return OutsideApplication(id=oid, company=company, title=title, requisition_id=req,
                              applied_on=on, status=ApplicationStatus.applied, linked_jd_id=linked,
                              created_at=NOW)


def run(new, tracked=(), out=(), scored=(), window=183):
    return match(new, tracked=list(tracked), outside=list(out), scored=list(scored),
                 window_days=window, today=TODAY)


# -- spec US2 scenarios ---------------------------------------------------------


def test_1_same_requisition_within_window():
    m = run(ad(2, req="JR_000123"), out=[outside(1, date(2026, 6, 6), req="JR-000123")])
    assert (m.kind, m.reason, m.against, m.age_days) == ("same", "requisition", "outside:1", 120)


def test_3_same_requisition_outside_window_is_no_match():
    assert run(ad(2, req="JR_000123"), out=[outside(1, date(2026, 3, 1), req="JR_000123")]) is None


def test_4_different_requisition_same_company_and_title_is_a_different_job():
    assert run(ad(2, req="JR_000456"), out=[outside(1, date(2026, 6, 6), req="JR_000123")]) is None


def test_5_same_company_and_title_without_numbers_is_possibly_same():
    m = run(ad(2), tracked=[(ad(1), applied(1, date(2026, 8, 1)))])
    assert (m.kind, m.reason, m.against) == ("possibly_same", "title", "application:1")


def test_worked_example_number_only_on_the_earlier_application():
    """The repost carries no number; the employer's receipt did. Must still ask."""
    m = run(ad(2), out=[outside(1, date(2026, 5, 5), req="JR_000123")])
    assert m.kind == "possibly_same" and m.age_days == 152


def test_identical_url_is_same():
    url = "https://jobs.example.invalid/fabrikam/1"
    m = run(ad(2, title="Something else", url=url), tracked=[(ad(1, url=url), applied(1, date(2026, 9, 1)))])
    assert (m.kind, m.reason) == ("same", "url")


# -- edge cases ---------------------------------------------------------------


def test_window_boundary():
    req = "JR_000123"
    on_182 = date.fromordinal(TODAY.toordinal() - 182)
    on_183 = date.fromordinal(TODAY.toordinal() - 183)
    assert run(ad(2, req=req), out=[outside(1, on_182, req=req)]) is not None
    assert run(ad(2, req=req), out=[outside(1, on_183, req=req)]) is None


def test_outcome_is_ignored():
    m = run(ad(2, req="JR_000123"),
            tracked=[(ad(1, req="JR_000123"), applied(1, date(2026, 8, 1), ApplicationStatus.withdrew))])
    assert m.kind == "same"


def test_different_company_same_title_is_nothing():
    assert run(ad(2), tracked=[(ad(1, company="Northwind Freight"), applied(1, date(2026, 8, 1)))]) is None


def test_unapplied_tracked_ads_do_not_count():
    unapplied = Application(jd_id=1, status=ApplicationStatus.not_applied, updated_at=NOW)
    assert run(ad(2), tracked=[(ad(1), unapplied)]) is None


def test_a_linked_outside_record_is_not_counted_twice():
    assert run(ad(2), out=[outside(1, date(2026, 8, 1), linked=5)]) is None


def test_another_scored_ad_with_the_same_number_matches():
    m = run(ad(2, req="JR_000123"), scored=[(ad(1, req="JR_000123"), date(2026, 10, 3))])
    assert (m.kind, m.against) == ("same", "ad:1")


def test_the_ad_never_matches_itself():
    assert run(ad(1, req="JR_000123"), tracked=[(ad(1, req="JR_000123"), applied(1, date(2026, 9, 1)))]) is None


def test_same_beats_possibly_same():
    m = run(ad(2, req="JR_000123"),
            tracked=[(ad(1), applied(1, date(2026, 9, 1)))],
            out=[outside(3, date(2026, 6, 1), req="JR_000123")])
    assert (m.kind, m.against) == ("same", "outside:3")


def test_rule_off():
    assert run(ad(2, req="JR_000123"), out=[outside(1, date(2026, 9, 1), req="JR_000123")], window=None) is None


def test_title_normalisation():
    assert normalise_title("Engineering Manager – (Hybrid)") == normalise_title("engineering manager hybrid")
    assert normalise_title("Senior Engineering Manager") != normalise_title("Engineering Manager")
