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
