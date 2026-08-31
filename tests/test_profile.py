"""Unit tests for the profile loader, run against profile.example/."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from jobagent.core.models import EvidenceStrength, Visibility
from jobagent.core.profile import (
    ProfileError,
    load_profile,
    summarize_profile,
)
from tests.conftest import edit_yaml


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_loads_example_profile(example_dir: Path) -> None:
    profile = load_profile(example_dir)

    assert profile.roles.person.name == "Sam Rivera"
    assert len(profile.roles.roles) == 6
    assert len(profile.stories.stories) == 6
    assert "Voice" in profile.voice
    assert profile.assets.target_filters.max_commute_minutes == 45


def test_scorer_only_visibility_parses(example_dir: Path) -> None:
    profile = load_profile(example_dir)
    legacy = next(c for c in profile.roles.ai_capability if c.id == "legacy_ml")
    assert legacy.visibility is Visibility.scorer_only


def test_linked_story_is_preserved(example_dir: Path) -> None:
    profile = load_profile(example_dir)
    payments = next(r for r in profile.roles.roles if r.id == "payments_lead")
    linked = {b.linked_story for b in payments.bullets if b.linked_story}
    assert "incremental_replatform" in linked


def test_summary_counts(example_dir: Path) -> None:
    summary = summarize_profile(load_profile(example_dir))

    assert summary.section_counts["roles"] == 6
    assert summary.section_counts["stories"] == 6
    assert summary.section_counts["earlier_career"] == 5

    # One scorer_only entry in the example (legacy_ml).
    assert summary.visibility_breakdown[Visibility.scorer_only.value] == 1
    assert summary.visibility_breakdown[Visibility.summary.value] == 5

    # Breakdown covers every evidence level and sums to a positive total.
    assert set(summary.evidence_breakdown) == {
        e.value for e in EvidenceStrength
    }
    assert sum(summary.evidence_breakdown.values()) > 0


# --------------------------------------------------------------------------- #
# Malformed input
# --------------------------------------------------------------------------- #


def test_missing_directory() -> None:
    with pytest.raises(ProfileError, match="Profile directory not found"):
        load_profile("/no/such/profile/dir")


def test_missing_file(profile_factory) -> None:
    def mutate(d: Path) -> None:
        (d / "stories.yaml").unlink()

    with pytest.raises(ProfileError, match="Profile file not found"):
        load_profile(profile_factory(mutate))


def test_bad_yaml_reports_filename_and_line(profile_factory) -> None:
    def mutate(d: Path) -> None:
        # Unterminated quoted string -> scanner error with a position mark.
        (d / "roles.yaml").write_text(
            'person:\n  name: "unterminated\n', encoding="utf-8"
        )

    with pytest.raises(ProfileError) as excinfo:
        load_profile(profile_factory(mutate))

    message = str(excinfo.value)
    assert "roles.yaml" in message
    # filename:line:col — a real line number, not a traceback.
    assert re.search(r"roles\.yaml:\d+:\d+:", message)
    assert "Traceback" not in message


def test_invalid_visibility(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "roles.yaml",
            lambda data: data["roles"][0].__setitem__("visibility", "hidden"),
        )

    with pytest.raises(ProfileError) as excinfo:
        load_profile(profile_factory(mutate))

    message = str(excinfo.value)
    assert "visibility" in message
    assert "hidden" in message


def test_invalid_evidence_strength(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "roles.yaml",
            lambda data: data["roles"][0]["bullets"][0].__setitem__(
                "evidence_strength", "medium"
            ),
        )

    with pytest.raises(ProfileError) as excinfo:
        load_profile(profile_factory(mutate))

    assert "evidence_strength" in str(excinfo.value)


def test_dangling_linked_story(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "roles.yaml",
            lambda data: data["roles"][0]["bullets"][0].__setitem__(
                "linked_story", "no_such_story"
            ),
        )

    with pytest.raises(ProfileError) as excinfo:
        load_profile(profile_factory(mutate))

    message = str(excinfo.value)
    assert "no_such_story" in message
    assert "unknown story" in message


def test_unknown_question_type(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "stories.yaml",
            lambda data: data["stories"][0]["question_types"].append("banter"),
        )

    with pytest.raises(ProfileError) as excinfo:
        load_profile(profile_factory(mutate))

    assert "banter" in str(excinfo.value)
    assert "question_type_vocabulary" in str(excinfo.value)


def test_duplicate_story_id(profile_factory) -> None:
    def mutate(d: Path) -> None:
        def dup(data: dict) -> None:
            data["stories"][1]["id"] = data["stories"][0]["id"]

        edit_yaml(d / "stories.yaml", dup)

    with pytest.raises(ProfileError, match="duplicate id"):
        load_profile(profile_factory(mutate))


def test_unknown_key_is_rejected(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "roles.yaml",
            lambda data: data["roles"][0].__setitem__("titel", "typo"),
        )

    with pytest.raises(ProfileError) as excinfo:
        load_profile(profile_factory(mutate))

    assert "titel" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Role periods: bare year, year-month, and the `present` sentinel
# --------------------------------------------------------------------------- #


def test_bare_year_period_normalises_to_string(example_dir: Path) -> None:
    # profile.example uses bare ints; YAML hands them over as int, and they
    # must come out as strings so callers never have to handle both.
    profile = load_profile(example_dir)

    assert profile.roles.roles[0].start == "2025"
    assert profile.roles.roles[0].end == "2026"


def test_year_month_period_is_preserved(profile_factory) -> None:
    def mutate(d: Path) -> None:
        def change(data: dict) -> None:
            data["roles"][0]["start"] = "2017-07"
            data["roles"][0]["end"] = "2018-10"

        edit_yaml(d / "roles.yaml", change)

    profile = load_profile(profile_factory(mutate))

    assert profile.roles.roles[0].start == "2017-07"
    assert profile.roles.roles[0].end == "2018-10"


def test_present_is_accepted_as_end(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "roles.yaml",
            lambda data: data["roles"][0].__setitem__("end", "present"),
        )

    profile = load_profile(profile_factory(mutate))

    assert profile.roles.roles[0].end == "present"


def test_present_is_rejected_as_start(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "roles.yaml",
            lambda data: data["roles"][0].__setitem__("start", "present"),
        )

    with pytest.raises(ProfileError) as excinfo:
        load_profile(profile_factory(mutate))

    assert "start" in str(excinfo.value)


@pytest.mark.parametrize("bad", ["July 2017", "2017-13", "17-07", "2017-7"])
def test_malformed_period_is_rejected(profile_factory, bad: str) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "roles.yaml",
            lambda data: data["roles"][0].__setitem__("start", bad),
        )

    with pytest.raises(ProfileError) as excinfo:
        load_profile(profile_factory(mutate))

    assert bad in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Optional fields added for the real profile
# --------------------------------------------------------------------------- #


def test_citizenship_is_optional(example_dir: Path) -> None:
    # profile.example omits it entirely.
    assert load_profile(example_dir).roles.person.citizenship is None


def test_citizenship_is_preserved(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "roles.yaml",
            lambda data: data["person"].__setitem__(
                "citizenship", "Dual Australian and Canadian — no sponsorship."
            ),
        )

    profile = load_profile(profile_factory(mutate))

    assert profile.roles.person.citizenship is not None
    assert "no sponsorship" in profile.roles.person.citizenship


def test_role_tech_defaults_to_empty(example_dir: Path) -> None:
    assert load_profile(example_dir).roles.roles[0].tech == []


def test_role_tech_is_preserved(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "roles.yaml",
            lambda data: data["roles"][0].__setitem__(
                "tech", ["C#/.NET", "Angular 5+", "MS SQL Server"]
            ),
        )

    profile = load_profile(profile_factory(mutate))

    assert profile.roles.roles[0].tech == ["C#/.NET", "Angular 5+", "MS SQL Server"]


def test_max_commute_basis_is_optional(example_dir: Path) -> None:
    assert load_profile(example_dir).assets.target_filters.max_commute_basis is None


def test_narrative_defaults_to_empty(example_dir: Path) -> None:
    narrative = load_profile(example_dir).assets.narrative

    assert narrative.spine is None
    assert narrative.threads == []
    assert narrative.consistency_rules == []


def test_narrative_is_preserved(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "assets.yaml",
            lambda data: data.__setitem__(
                "narrative",
                {
                    "spine": "One story, told the same way.",
                    "threads": ["Industry depth", "Startup building"],
                    "consistency_rules": ["Departure reasons are canonical."],
                },
            ),
        )

    narrative = load_profile(profile_factory(mutate)).assets.narrative

    assert narrative.spine == "One story, told the same way."
    assert len(narrative.threads) == 2
    assert narrative.consistency_rules == ["Departure reasons are canonical."]


def test_role_note_for_scorer_is_preserved(profile_factory) -> None:
    def mutate(d: Path) -> None:
        edit_yaml(
            d / "roles.yaml",
            lambda data: data["roles"][0].__setitem__(
                "note_for_scorer", "Title understates the scope."
            ),
        )

    profile = load_profile(profile_factory(mutate))

    assert profile.roles.roles[0].note_for_scorer == "Title understates the scope."