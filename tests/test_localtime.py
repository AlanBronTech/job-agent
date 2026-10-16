"""REVIEW-2026-10-16 D11: one time zone on the page — Sydney, not UTC."""

from __future__ import annotations

from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader

from jobagent.timefmt import local


def test_a_utc_time_is_shown_in_sydney():
    scored = datetime(2026, 10, 16, 0, 18, tzinfo=timezone.utc)
    assert local(scored).strftime("%-d %b %Y %H:%M") == "16 Oct 2026 11:18"  # AEDT, +11


def test_a_naive_time_is_already_local_and_left_alone():
    modified = datetime(2026, 10, 16, 11, 28)
    assert local(modified) == modified


def test_the_job_page_shows_the_scored_time_in_sydney():
    from jobagent.web.app import _register_filters

    env = Environment(loader=FileSystemLoader("jobagent/web/templates"))
    _register_filters(env)
    html = env.from_string('{{ t | local("%H:%M") }}').render(
        t=datetime(2026, 10, 16, 0, 18, tzinfo=timezone.utc))
    assert html == "11:18"


def test_assessment_md_dates_the_score_in_sydney():
    from jobagent.adapters.docs import assessment_markdown
    from tests.quality_seed import northwind, northwind_assessment

    a = northwind_assessment()
    a.scored_at = datetime(2026, 10, 15, 22, 0, tzinfo=timezone.utc)  # 16 Oct, 09:00 in Sydney
    assert "**Scored:** 2026-10-16" in assessment_markdown(a, northwind(), [])
