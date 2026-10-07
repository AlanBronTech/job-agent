"""Spec 003 on the worked example (invented): what the writer is shown, what blocks.

SC-001 is proved in parts: the role kind and exclusions here (US1); the reuse
caps join this file with US5.
"""

from __future__ import annotations

from datetime import date

import pytest

from jobagent.core.generate import build_cover_letter, build_resume
from jobagent.core.profile import load_profile
from jobagent.core.validation import Severity
from tests.quality_seed import (
    PEOPLE,
    TECHNICAL,
    RoutedClient,
    contoso,
    northwind,
    northwind_assessment,
)

TODAY = date(2026, 10, 7)
EXIT_BULLET = "ending in a managed exit"


@pytest.fixture
def profile(example_dir):
    return load_profile(example_dir)


def selection(**overrides) -> dict:
    data = {
        "tagline": "Engineering Leader  ·  Team Builder",
        "profile_paragraphs": ["Builds teams.", "Now leading a team."],
        "highlights": [
            {"label": "Team building", "text": "Recruited and onboarded people.",
             "source_ref": "recent_manager.0"},
        ],
        "skill_categories": ["ai_and_automation", "frontend", "delivery", "leadership"],
        "roles": [{"role_id": "recent_manager", "bullet_refs": ["recent_manager.0"]}],
        "earlier_career_ids": [],
    }
    data.update(overrides)
    return data


def resume(profile, payload, kind=PEOPLE, jd=None):
    client = RoutedClient({"generate_resume": payload})
    built = build_resume(jd or northwind(), profile, northwind_assessment(),
                         client=client, today=TODAY, kind=kind)
    return built, client.prompts["generate_resume"][0]


def rules(built):
    return {(i.rule, i.severity) for i in built.issues}


def test_the_excluded_story_is_never_shown_for_a_people_focused_ad(profile):
    built, prompt = resume(profile, selection())
    assert EXIT_BULLET not in prompt and "recent_manager.3" not in prompt
    assert "people-focused" in prompt and PEOPLE.reason in prompt
    assert not any(i.rule == "excluded evidence" for i in built.issues)


def test_a_technical_lead_ad_still_sees_it(profile):
    _, prompt = resume(profile, selection(), kind=TECHNICAL, jd=contoso())
    assert EXIT_BULLET in prompt


def test_citing_excluded_evidence_blocks_and_keeps_it_off_the_page(profile):
    payload = selection(
        roles=[{"role_id": "recent_manager", "bullet_refs": ["recent_manager.0", "recent_manager.3"]}],
        highlights=[{"label": "Hard calls", "text": "Managed an exit.", "source_ref": "recent_manager.3"}],
    )
    built, _ = resume(profile, payload)
    excluded = [i for i in built.issues if i.rule == "excluded evidence"]
    assert len(excluded) == 2 and all(i.severity is Severity.blocker for i in excluded)
    rendered = " ".join(b for role in built.content.roles for b in role.bullets)
    assert EXIT_BULLET not in rendered


def test_skills_are_ordered_by_kind(profile):
    built, _ = resume(profile, selection())
    labels = [s.label for s in built.content.skills]
    assert labels[:2] == ["LEADERSHIP", "DELIVERY"]


def test_an_ai_highlight_first_is_flagged_for_a_people_focused_ad(profile):
    payload = selection(highlights=[
        {"label": "AI in production", "text": "Introduced agentic coding tooling.",
         "source_ref": "recent_manager.1"}])
    built, _ = resume(profile, payload)
    assert ("lead not on-kind", Severity.warning) in rules(built)
    clean, _ = resume(profile, selection())
    assert ("lead not on-kind", Severity.warning) not in rules(clean)


def test_the_unused_list_does_not_report_excluded_evidence(profile):
    built, _ = resume(profile, selection())
    assert "underperformer" not in {u.id for u in built.unused}


def test_the_letter_is_not_shown_the_excluded_story(profile):
    client = RoutedClient({"generate_cover_letter": {"paragraphs": [[
        {"text": "I recruited and onboarded nine people.", "cites": ["recent_manager.0"]}]]}})
    build_cover_letter(northwind(), profile, northwind_assessment(), client=client, kind=PEOPLE)
    prompt = client.prompts["generate_cover_letter"][0]
    assert "underperformer" not in prompt and EXIT_BULLET not in prompt


# -- US5: story reuse and defensive phrasing ----------------------------------------


def test_one_story_four_times_blocks(profile):
    """The worked example: the scope story in PROFILE, a highlight, a bullet, and more."""
    payload = selection(
        profile_refs=[["scope_disagreement"], []],
        highlights=[
            {"label": "Team building", "text": "Recruited people.", "source_ref": "recent_manager.0"},
            {"label": "Disagree and commit", "text": "Advised, then delivered.", "source_ref": "startup_em.1"},
            {"label": "Scope", "text": "Argued for a narrower release.", "source_ref": "scope_disagreement"},
        ],
        roles=[{"role_id": "startup_em", "bullet_refs": ["startup_em.0", "startup_em.1"]}],
    )
    built, _ = resume(profile, payload)
    reused = [i for i in built.issues if i.rule == "story reused"]
    assert len(reused) == 1 and "4 times" in reused[0].detail
    assert reused[0].severity is Severity.blocker


def test_profile_plus_a_bullet_blocks_even_at_two(profile):
    payload = selection(
        profile_refs=[["startup_em.1"], []],
        roles=[{"role_id": "startup_em", "bullet_refs": ["startup_em.1"]}],
    )
    built, _ = resume(profile, payload)
    assert any(i.rule == "story reused" and "PROFILE" in i.detail for i in built.issues)


def test_a_highlight_and_a_bullet_is_allowed(profile):
    payload = selection(
        highlights=[{"label": "Scope", "text": "Advised, then delivered.", "source_ref": "startup_em.1"}],
        roles=[{"role_id": "startup_em", "bullet_refs": ["startup_em.1"]}],
    )
    built, _ = resume(profile, payload)
    assert not any(i.rule == "story reused" for i in built.issues)


def letter_payload(*paragraphs):
    return {"paragraphs": [[{"text": t, "cites": c} for t, c in p] for p in paragraphs]}


def test_a_letter_telling_one_story_in_two_paragraphs_blocks(profile):
    payload = letter_payload(
        [("I advised against over-scoping, then delivered.", ["startup_em.1"])],
        [("When overruled I committed to the wider scope.", ["scope_disagreement"])],
    )
    client = RoutedClient({"generate_cover_letter": payload})
    built = build_cover_letter(northwind(), profile, northwind_assessment(), client=client, kind=PEOPLE)
    assert any(i.rule == "story reused" for i in built.issues)
    assert len(client.prompts["generate_cover_letter"]) == 2  # regenerated once


def test_defensive_phrasing_blocks_and_contrast_warns(profile):
    from jobagent.core.validation import validate_prose

    issues = validate_prose("This ad is asking for a coach.", profile)
    assert ("banned phrase", Severity.blocker) in {(i.rule, i.severity) for i in issues}
    issues = validate_prose(
        "I led people, not just code. I chose to coach rather than replace.", profile)
    assert ("contrast phrasing", Severity.warning) in {(i.rule, i.severity) for i in issues}
    assert not validate_prose("I chose to coach rather than replace.", profile)


# -- US6: one company sentence, from the ad -------------------------------------------


def company_letter(quote):
    sentence = {"text": "You build route planning for regional freight carriers.", "cites": ["ad"]}
    if quote:
        sentence["quote"] = quote
    return {"paragraphs": [[sentence,
                            {"text": "I recruited and onboarded nine people.", "cites": ["recent_manager.0"]}]]}


def write_letter(profile, payload, jd=None):
    client = RoutedClient({"generate_cover_letter": [payload]})
    return build_cover_letter(jd or northwind(), profile, northwind_assessment(), client=client, kind=PEOPLE)


def test_a_company_sentence_quoting_the_ad_passes(profile):
    built = write_letter(profile, company_letter("route planning for regional freight carriers"))
    assert built.issues == [] and "route planning" in built.text


def test_an_invented_quote_blocks(profile):
    built = write_letter(profile, company_letter("the market leader in freight software"))
    assert any(i.rule == "company claim not in ad" for i in built.issues)


def test_an_ad_without_a_company_description_needs_no_company_sentence(profile):
    from tests.quality_seed import fabrikam

    payload = {"paragraphs": [[{"text": "I recruited and onboarded nine people.", "cites": ["recent_manager.0"]}]]}
    built = write_letter(profile, payload, jd=fabrikam())
    assert built.issues == []


def test_two_company_sentences_warn(profile):
    payload = company_letter("route planning for regional freight carriers")
    payload["paragraphs"].append([{"text": "Regional freight is your market.", "cites": ["ad"],
                                   "quote": "regional freight carriers"}])
    built = write_letter(profile, payload)
    assert ("company sentences", Severity.warning) in rules(built)
