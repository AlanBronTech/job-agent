"""Unit tests for the output filters in `profile/voice.md`.

These are the checks standing between a generated document and Alan sending
something that costs him an interview, so they get tested harder than most of
the codebase. No model is involved: a validator that needs one is a second
opinion, not a check.
"""

from __future__ import annotations

import pytest

from jobagent.core.profile import load_profile
from jobagent.core.validation import (
    Severity,
    banned_phrases,
    blockers,
    validate_prose,
)


@pytest.fixture
def profile(profile_factory):
    return load_profile(profile_factory())


def rules(issues) -> set[str]:
    return {issue.rule for issue in issues}


# --------------------------------------------------------------------------- #
# The age-signal policy — the rule Alan is most exposed on
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "I bring 25 years of experience to the role.",
        "With 20+ years of experience in the industry.",
        "Over 20 years leading engineering teams.",
        "Two decades of delivery leadership.",
        "I have been building software since 2006.",
        "A career spanning banking and government.",
    ],
)
def test_career_length_is_a_blocker(text, profile) -> None:
    issues = validate_prose(text, profile)

    assert "age signal" in rules(issues)
    assert blockers(issues)


def test_a_role_date_is_not_a_career_length(profile) -> None:
    """voice.md is explicit: role dates are shown, including pre-2017 founder
    dates. It is summing them that is banned."""
    issues = validate_prose(
        "Co-founder & CTO, Home Design Directory (2006-16).", profile
    )

    assert "age signal" not in rules(issues)


def test_a_team_size_is_not_a_career_length(profile) -> None:
    issues = validate_prose("Led 15 engineers across three product streams.", profile)

    assert "age signal" not in rules(issues)


# --------------------------------------------------------------------------- #
# Invented numbers
# --------------------------------------------------------------------------- #


def test_a_number_absent_from_the_profile_is_a_blocker(profile) -> None:
    issues = validate_prose("Led a team of 4711 engineers.", profile)

    assert "unsupported number" in rules(issues)
    assert issues[0].severity is Severity.blocker


def test_a_number_present_in_the_profile_passes(profile) -> None:
    """Taken from the example profile itself rather than hardcoded, so the
    test does not go stale when the fixture changes."""
    from jobagent.core.validation import _profile_numbers

    number = next(n for n in sorted(_profile_numbers(profile), key=len, reverse=True) if len(n) > 2)

    issues = validate_prose(f"Delivered against {number} of them.", profile)

    assert "unsupported number" not in rules(issues)


def test_small_counts_are_not_traced(profile) -> None:
    """"three squads" and "2 days" carry no claim, and tracing them produces
    noise that buries the real finding."""
    issues = validate_prose("Ran 3 squads over 2 releases.", profile)

    assert "unsupported number" not in rules(issues)


# --------------------------------------------------------------------------- #
# Voice
# --------------------------------------------------------------------------- #


def test_banned_phrases_come_from_voice_md(profile) -> None:
    phrases = banned_phrases(profile.voice)

    assert "i am thrilled" in phrases
    # Slash alternates are separated.
    assert "passionate about" in phrases
    # So are comma-separated lists.
    assert "team player" in phrases
    # Rules phrased as judgment are not treated as literal phrases.
    assert not any(phrase.startswith("any sentence") for phrase in phrases)


def test_a_banned_phrase_is_a_blocker(profile) -> None:
    issues = validate_prose("I am thrilled to apply for this role.", profile)

    assert "banned phrase" in rules(issues)


def test_a_banned_opening_is_caught(profile) -> None:
    issues = validate_prose(
        "I am writing to apply for the Engineering Manager position.", profile
    )

    assert "banned opening" in rules(issues)


def test_clean_prose_passes(profile) -> None:
    issues = validate_prose(
        "I led the team that rebuilt the payments platform. The migration "
        "shipped on schedule and cut incident volume.",
        profile,
    )

    assert issues == []


# --------------------------------------------------------------------------- #
# Length and leakage
# --------------------------------------------------------------------------- #


def test_an_over_length_letter_is_a_blocker(profile) -> None:
    issues = validate_prose("word " * 400, profile, max_words=350, context="The letter")

    assert "length" in rules(issues)


def test_a_letter_within_the_limit_passes(profile) -> None:
    issues = validate_prose("word " * 300, profile, max_words=350)

    assert "length" not in rules(issues)


# --------------------------------------------------------------------------- #
# Text copied verbatim out of the profile
# --------------------------------------------------------------------------- #


def test_a_cross_reference_in_a_bullet_is_caught() -> None:
    """A real bullet ends "— see ai_capability.research_agent for evidence and
    current status", and copied verbatim it went onto a generated resume."""
    from jobagent.core.validation import validate_rendered

    issues = validate_rendered(
        "Building an agentic system — see ai_capability.research_agent for status.",
        context="Bullet bron_consulting.0",
    )

    assert [issue.rule for issue in issues] == ["internal reference"]
    assert issues[0].severity is Severity.blocker


def test_an_internal_field_name_in_a_bullet_is_caught() -> None:
    from jobagent.core.validation import validate_rendered

    issues = validate_rendered("Delivered the platform. note_for_scorer: thin.")

    assert [issue.rule for issue in issues] == ["internal reference"]


def test_a_career_length_in_a_profile_bullet_is_still_caught() -> None:
    from jobagent.core.validation import validate_rendered

    issues = validate_rendered("Brought 25 years of experience to the team.")

    assert [issue.rule for issue in issues] == ["age signal"]


def test_an_ordinary_bullet_passes_unflagged() -> None:
    from jobagent.core.validation import validate_rendered

    assert validate_rendered("Led 15 engineers across three product lines.") == []


def test_profile_numbers_are_not_traced_in_rendered_text() -> None:
    """They came from the profile by definition; tracing them is noise."""
    from jobagent.core.validation import validate_rendered

    assert validate_rendered("Cut incident volume by 4711 per cent.") == []


@pytest.mark.parametrize(
    "text",
    [
        "Re-platformed the legacy stack incrementally over 2 years.",
        "Ran the programme over 3 years alongside delivery.",
    ],
)
def test_a_project_duration_is_not_a_career_length(text, profile) -> None:
    """This fired on a real profile bullet. A blocker that cries wolf trains
    its reader to click past the ones that matter."""
    issues = validate_prose(text, profile)

    assert "age signal" not in rules(issues)


def test_a_large_over_n_years_is_still_caught(profile) -> None:
    issues = validate_prose("Over 20 years leading teams.", profile)

    assert "age signal" in rules(issues)


def test_a_small_figure_attached_to_experience_is_still_caught(profile) -> None:
    issues = validate_prose("I bring 8 years of experience.", profile)

    assert "age signal" in rules(issues)


# --------------------------------------------------------------------------- #
# What the number haystack covers, and what it deliberately does not
#
# `_check_numbers` blocks any figure absent from the haystack, so the set is
# the boundary between "traced to the profile" and "invented". Both directions
# have drawn blood: the haystack was hand-maintained and had drifted away from
# material the prompts actually carry, and widening it indiscriminately would
# license figures the profile forbids by name.
# --------------------------------------------------------------------------- #


def _numbers_in(text: str) -> set[str]:
    from jobagent.core.validation import _NUMBER_PATTERN

    return {m.group().replace(",", "") for m in _NUMBER_PATTERN.finditer(text)}


def test_every_number_the_model_may_reuse_is_supported(profile_factory) -> None:
    """The invariant the hand-maintained field list broke.

    Profile material `generate.py` puts in front of the model to reuse must be
    licensed by the validator, or a model gets blocked for following the
    instruction it was given. `stories.explanations` reaches the cover-letter
    and answers prompts under "use these words, do not invent others", and was
    absent from the haystack for as long as the list was written by hand.

    The example profile ships `salary_expectation: TODO`, so the figures are
    written in here — without them this test passes against the very bug it
    exists to catch. They are invented: this repo is public, and Alan's real
    expectation is not a number that belongs in it.

    Scoped to the text, not the rendered prompt: `_render_catalogue` adds its
    own digits — `easy_signs.0` reference keys and `[2015-17]` date ranges —
    which are scaffolding for the model to navigate by, not claims it may make.
    """
    from tests.conftest import edit_yaml
    from jobagent.core.generate import _render_stories, build_catalogue
    from jobagent.core.validation import _profile_numbers

    def fill_in(dst):
        edit_yaml(
            dst / "stories.yaml",
            lambda data: data["explanations"].update(
                {
                    "salary_expectation": "Targeting $123,000; the floor is $99,000.",
                    "why_leaving_current": "The contract ends after 47 months.",
                }
            ),
        )

    profile = load_profile(profile_factory(fill_in))

    reusable = "\n".join(
        [
            *build_catalogue(profile).values(),  # bullets, copied verbatim
            _render_stories(profile),  # stories and the agreed explanations
            *(skill for values in profile.roles.skills.values() for skill in values),
        ]
    )

    assert {"123000", "99000", "47"} <= _numbers_in(reusable)  # the fixture bites
    assert _numbers_in(reusable) <= _profile_numbers(profile)


@pytest.mark.parametrize(
    "path, mutate",
    [
        ("stories.yaml", lambda d: d["explanations"].update({"outside_interests": "Ran 4711 km."})),
        ("stories.yaml", lambda d: d["stories"][0].update({"label": "Cutover of 4711 accounts"})),
        ("roles.yaml", lambda d: d["person"]["certifications"].append(
            {"name": "Certified Operator 4711", "issuer": "Example Board"})),
        ("roles.yaml", lambda d: d["person"]["education"][0].update(
            {"institution": "Institute 4711"})),
        ("assets.yaml", lambda d: d["target_filters"].update({"min_salary_aud": 4711})),
    ],
    ids=["explanations", "story-label", "certifications", "education", "target-filters"],
)
def test_fields_the_hand_written_list_omitted_are_covered(
    path, mutate, profile_factory
) -> None:
    """Every field an outside review found missing from the old list.

    These are the drift the walk exists to prevent: each was in the schema, in
    the loaded profile, and absent from the haystack, so a figure taken from
    any of them read as fabricated.
    """
    from tests.conftest import edit_yaml
    from jobagent.core.validation import _profile_numbers

    profile = load_profile(
        profile_factory(lambda dst: edit_yaml(dst / path, mutate))
    )

    assert "4711" in _profile_numbers(profile)


def test_an_agreed_explanation_is_not_an_invented_number(profile_factory) -> None:
    """The live regression. A salary expectation is prose the model is told to
    reuse verbatim, and the figure in it must not read as fabricated."""
    from tests.conftest import edit_yaml

    def set_salary(dst):
        edit_yaml(
            dst / "stories.yaml",
            lambda data: data["explanations"].update(
                {"salary_expectation": "Targeting $123,000, and the floor is $99,000."}
            ),
        )

    profile = load_profile(profile_factory(set_salary))

    issues = validate_prose("My expectation is $123,000.", profile)

    assert "unsupported number" not in rules(issues)


def test_a_scorer_only_note_does_not_license_a_number(profile_factory) -> None:
    """The reason the haystack is not simply every string in the model.

    A real `note_for_scorer` reads "NEVER PUBLISH THE USER COUNT. The
    deployment has 22 users." Scanning it would make 22 a supported figure, so
    a draft publishing the one number the profile forbids would validate
    clean — the invariant inverted by the check meant to enforce it.
    """
    from tests.conftest import edit_yaml
    from jobagent.core.validation import _profile_numbers

    def add_note(dst):
        edit_yaml(
            dst / "roles.yaml",
            lambda data: data["founder_track_record"][0].update(
                {"note_for_scorer": "NEVER PUBLISH THIS. The deployment has 4711 users."}
            ),
        )

    profile = load_profile(profile_factory(add_note))

    assert "4711" not in _profile_numbers(profile)
    assert "unsupported number" in rules(
        validate_prose("The deployment has 4711 users.", profile)
    )


def test_a_scorer_only_phrase_matches_across_whitespace(profile) -> None:
    """Hidden labels are checked as phrases, not raw substrings.

    The old substring match missed the same label split across whitespace. The
    phrase matcher should still catch it, because the content is the same
    leakage regardless of line breaks.
    """
    issues = validate_prose(
        "I have an Applied\nML background in production systems.", profile
    )

    assert "scorer-only content" in rules(issues)


def test_voice_md_does_not_license_a_number(profile) -> None:
    """voice.md is the rules, not the evidence.

    It quotes "25 years" and "20+ years" as examples of banned age signals and
    states Alan's age. Scanning it made every one of those a supported figure,
    so the file written to prohibit an age signal was licensing one.
    """
    from jobagent.core.validation import _profile_numbers

    assert _numbers_in(profile.voice) - _profile_numbers(profile)


def test_a_contact_detail_does_not_license_a_number(profile) -> None:
    """The phone number is rendered deterministically onto the contact line and
    never passes through generated prose, so its digits are not evidence.

    A pin, not a regression: the old hand-written list omitted `phone` too. It
    is here because the walk that replaced that list would otherwise pick the
    field up, and on the real profile that licensed "379" as a headcount.
    """
    from jobagent.core.validation import _profile_numbers

    digits = _numbers_in(profile.roles.person.phone)

    assert digits and not digits & _profile_numbers(profile)
