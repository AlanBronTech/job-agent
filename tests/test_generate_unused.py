"""`unused_entries` — profile content the model was shown and used nowhere.

DataLlama was dropped from a generated resume twice. The renderer blocks an
ongoing venture from EXPERIENCE and EARLIER CAREER, so a CAREER HIGHLIGHT is its
only route onto the page; the model chose five other highlights and the entry
vanished. Both times the omission was invisible in the finished document — the
only way to notice was to already know it should have been there.

So this reports, and does not enforce. Which evidence an ad rewards is the
model's judgement and usually it is right. A validator cannot make that call; a
reader can, and only while still reading.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from jobagent.cli import generate as generate_cli
from jobagent.core.generate import (
    UnusedEntry,
    _Highlight,
    _ResumeSelection,
    _RoleSelection,
    unused_entries,
)
from jobagent.core.profile import load_profile
from tests.conftest import edit_yaml


def selection(**overrides) -> _ResumeSelection:
    fields = {
        "tagline": "Engineering Manager",
        "profile_paragraphs": ["One.", "Two."],
        "highlights": [],
        "skill_categories": [],
        "roles": [],
        "earlier_career_ids": [],
    }
    fields.update(overrides)
    return _ResumeSelection(**fields)


@pytest.fixture
def profile(profile_factory):
    return load_profile(profile_factory())


@pytest.fixture
def ongoing_profile(profile_factory):
    """One founder venture still running, which is DataLlama's shape."""

    def mutate(directory):
        def change(data):
            data["founder_track_record"][2]["end"] = "present"

        edit_yaml(directory / "roles.yaml", change)

    return load_profile(profile_factory(mutate))


def ids(entries: list[UnusedEntry]) -> list[str]:
    return [entry.id for entry in entries]


def test_an_entry_used_nowhere_is_reported(profile):
    result = unused_entries(selection(), profile)

    # Nothing was selected, so every renderable entry is unused.
    assert "recent_manager" in ids(result)
    assert "oss_platform" in ids(result)


def test_a_selected_role_is_not_reported(profile):
    result = unused_entries(
        selection(roles=[_RoleSelection(role_id="recent_manager")]), profile
    )

    assert "recent_manager" not in ids(result)


def test_a_bullet_reference_counts_as_using_its_entry(profile):
    """`payments_lead.2` is evidence that payments_lead reached the page."""
    result = unused_entries(
        selection(
            roles=[
                _RoleSelection(
                    role_id="recent_manager", bullet_refs=["payments_lead.2"]
                )
            ]
        ),
        profile,
    )

    assert "payments_lead" not in ids(result)


def test_a_highlight_citation_counts_as_using_its_entry(profile):
    result = unused_entries(
        selection(
            highlights=[
                _Highlight(
                    label="AI", text="...", source_ref="agentic_coding_adoption.0"
                )
            ]
        ),
        profile,
    )

    assert "agentic_coding_adoption" not in ids(result)


def test_an_earlier_career_id_counts_as_used(profile):
    result = unused_entries(selection(earlier_career_ids=["gov_systems"]), profile)

    assert "gov_systems" not in ids(result)


def test_a_founder_id_in_earlier_career_counts_as_used(profile):
    """`earlier_career_ids` accepts founder ids too — `_assemble` resolves both."""
    result = unused_entries(selection(earlier_career_ids=["mvp_venture"]), profile)

    assert "mvp_venture" not in ids(result)


def test_scorer_only_entries_are_never_reported(profile):
    """They can never be rendered, so listing them would be permanent noise."""
    result = unused_entries(selection(), profile)

    assert "legacy_ml" not in ids(result)


def test_an_ongoing_venture_is_flagged_and_sorted_first(ongoing_profile):
    result = unused_entries(selection(), ongoing_profile)

    assert result[0].id == "oss_platform"
    assert result[0].highlight_only is True
    # It is the only entry whose sole route onto the page is a highlight.
    assert [e.id for e in result if e.highlight_only] == ["oss_platform"]


def test_strong_evidence_is_carried_through(profile):
    result = unused_entries(selection(), profile)
    by_id = {entry.id: entry for entry in result}

    assert by_id["recent_manager"].strong is True
    assert all(isinstance(entry.strong, bool) for entry in result)


def test_labels_come_from_whichever_field_the_group_uses(profile):
    by_id = {entry.id: entry for entry in unused_entries(selection(), profile)}

    # A role has `title`, a founder entry has `role`, an AI entry only `label`.
    assert "·" in by_id["recent_manager"].label
    assert "·" in by_id["oss_platform"].label
    assert by_id["ai_credentials"].label


def test_the_report_prints_even_with_no_validation_issues(monkeypatch, tmp_path):
    """The regression this guards against.

    `_report` returned early on a clean run, which would have hidden the list on
    exactly the runs where nothing else demands attention.
    """
    buffer = io.StringIO()
    monkeypatch.setattr(generate_cli, "console", Console(file=buffer, width=100))

    generate_cli._report(
        tmp_path,
        [],
        [],
        [
            UnusedEntry(
                id="oss_platform",
                group="founder_track_record",
                label="OSS Platform · Co-founder",
                strong=True,
                highlight_only=True,
            )
        ],
    )

    output = buffer.getvalue()
    assert "No validation issues" in output
    assert "Not used" in output
    assert "oss_platform" in output
    assert "only slot" in output


def test_nothing_is_printed_when_everything_was_used(monkeypatch, tmp_path):
    buffer = io.StringIO()
    monkeypatch.setattr(generate_cli, "console", Console(file=buffer, width=100))

    generate_cli._report(tmp_path, [], [], [])

    assert "Not used" not in buffer.getvalue()
