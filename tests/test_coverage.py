"""SC-003: every evidenced must-have on the resume, as a highlight or a bullet."""

from __future__ import annotations

from datetime import date

import pytest

from jobagent.core import coverage
from jobagent.core.generate import build_resume
from jobagent.core.models import MatchStatus, RequirementMatch
from jobagent.core.profile import load_profile
from tests.quality_seed import PEOPLE, RoutedClient, northwind, northwind_assessment


@pytest.fixture
def profile(example_dir):
    return load_profile(example_dir)


def statuses(rows):
    return {row.requirement.split()[0]: row.status for row in rows}


def test_three_evidenced_must_haves_and_a_gap(profile):
    rows = coverage.coverage(
        northwind_assessment(), profile,
        ["recent_manager.0", "startup_em.0", "consultancy_lead.1"],
    )
    assert statuses(rows) == {"Coaching": "covered", "Hiring": "covered",
                              "Partnering": "covered", "Freight": "gap"}
    assert coverage.issues(rows) == []


def test_a_missing_must_have_blocks(profile):
    rows = coverage.coverage(northwind_assessment(), profile, ["recent_manager.0"])
    missing = [i for i in coverage.issues(rows) if i.rule == "must-have missing"]
    assert {i.excerpt for i in missing} == {"startup_em.0", "consultancy_lead"}
    assert all(i.severity.value == "blocker" for i in missing)


def test_a_skills_keyword_alone_is_weak(profile):
    a = northwind_assessment()
    a.requirements = [RequirementMatch(requirement="Kubernetes in production",
                                       status=MatchStatus.met, evidence_ref="startup_em.0", note="x")]
    rows = coverage.coverage(a, profile, [], skills_text="Python, Kubernetes, AWS")
    assert rows[0].status == "weak"
    assert coverage.issues(rows)[0].severity.value == "warning"


def test_a_story_is_covered_by_a_bullet_that_tells_it(profile):
    a = northwind_assessment()
    a.requirements = [RequirementMatch(requirement="Disagree and commit", status=MatchStatus.met,
                                       evidence_ref="scope_disagreement", note="x")]
    assert coverage.coverage(a, profile, ["startup_em.1"])[0].status == "covered"


def test_excluded_evidence_is_not_demanded_and_unknown_refs_are_not_blocked(profile):
    a = northwind_assessment()
    a.requirements = [
        RequirementMatch(requirement="Addressing underperformance", status=MatchStatus.met,
                         evidence_ref="underperformer", note="x"),
        RequirementMatch(requirement="Differentiator", status=MatchStatus.met,
                         evidence_ref="some_differentiator", note="x"),
    ]
    rows = coverage.coverage(a, profile, [], excluded={"underperformer"})
    assert [r.status for r in rows] == ["not checkable"]
    assert coverage.must_cover(a, {"underperformer"}) == [("Differentiator", "some_differentiator")]


def test_the_resume_prompt_lists_what_must_be_covered_and_the_result_reports_it(profile):
    payload = {
        "tagline": "Engineering Leader", "profile_paragraphs": ["One.", "Two."],
        "highlights": [{"label": "Teams", "text": "Recruited people.", "source_ref": "recent_manager.0"}],
        "skill_categories": ["leadership"],
        "roles": [{"role_id": "recent_manager", "bullet_refs": ["recent_manager.0"]}],
        "earlier_career_ids": [],
    }
    client = RoutedClient({"generate_resume": payload})
    built = build_resume(northwind(), profile, northwind_assessment(), client=client,
                         today=date(2026, 10, 7), kind=PEOPLE)
    prompt = client.prompts["generate_resume"][0]
    assert "Hiring and building a healthy team culture  ->  cite startup_em.0" in prompt
    assert statuses(built.coverage)["Hiring"] == "missing"
    assert "must-have missing" in {i.rule for i in built.issues}
