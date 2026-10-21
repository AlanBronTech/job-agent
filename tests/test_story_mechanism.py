"""Story mechanism fields (REVIEW-2026-10-18 task 3): shown to the writer and the
claim check, and a false line never licenses a number. Invented content."""

from __future__ import annotations

from jobagent.core.generate import _render_stories, evidence_text
from jobagent.core.profile import load_profile
from jobagent.core.validation import _profile_numbers, validate_prose
from tests.conftest import edit_yaml

MECHANISM = {
    "sequence": ["Set up the new hosting and the release pipeline.", "Ported the code."],
    "how_it_worked": "The old server kept serving until the new one was ready.",
    "why_this_way": "A rewrite was too much work.",
    "cause_effect": ["Fortnightly releases followed from two-week sprints."],
    "not_true": ["The old and new systems ran side by side for 7777 days."],
}


def with_mechanism(profile_factory):
    def add(dst):
        edit_yaml(dst / "stories.yaml", lambda data: data["stories"][0].update(MECHANISM))
    return load_profile(profile_factory(add))


def test_the_writer_sees_the_order_the_causes_and_what_is_false(profile_factory):
    rendered = _render_stories(with_mechanism(profile_factory))
    assert rendered.index("Set up the new hosting") < rendered.index("Ported the code.")
    assert "cite the story id, not a step" in rendered
    assert "the only ones a sentence may claim" in rendered
    assert "NOT TRUE — never state or imply" in rendered
    assert "ran side by side" in rendered


def test_the_claim_check_reads_the_mechanism_too(profile_factory):
    profile = with_mechanism(profile_factory)
    text = evidence_text(profile, profile.stories.stories[0].id)
    assert "Fortnightly releases followed from two-week sprints." in text
    assert "NOT TRUE" in text and "side by side" in text


def test_a_number_in_a_false_line_licenses_nothing(profile_factory):
    profile = with_mechanism(profile_factory)
    assert "7777" not in _profile_numbers(profile)
    issues = validate_prose("They ran in parallel for 7777 days.", profile)
    assert any(i.rule == "unsupported number" for i in issues)


def test_a_story_without_the_fields_renders_as_before(profile_factory):
    rendered = _render_stories(load_profile(profile_factory()))
    assert "NOT TRUE" not in rendered and "sequence, in this order" not in rendered
