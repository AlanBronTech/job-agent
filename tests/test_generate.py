"""Unit tests for content selection and assembly.

The point of the design is that the model returns references and never types a
bullet, so the tests that matter are: a reference it invents is caught, a
`scorer_only` entry never reaches the page, and dates are computed rather than
asked for.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from jobagent.adapters.llm import LLMClient, LLMResponse, Provider
from jobagent.core.generate import (
    GenerateError,
    build_catalogue,
    build_resume,
    format_dates,
)
from jobagent.core.models import (
    FitAssessment,
    JobDescription,
    Verdict,
    WorkArrangement,
    WorkType,
)
from jobagent.core.profile import load_profile


@pytest.fixture
def profile(profile_factory):
    return load_profile(profile_factory())


@pytest.fixture
def jd() -> JobDescription:
    return JobDescription(
        id=1,
        title="Engineering Manager",
        company="Acme",
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        raw_text="Engineering Manager at Acme.",
        ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def assessment() -> FitAssessment:
    return FitAssessment(
        jd_id=1,
        overall_score=70,
        recruiter_screen_score=60,
        verdict=Verdict.apply,
        rationale="Good match.",
        target_role_match=True,
        target_role_note="Engineering Manager.",
        scored_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


class FakeClient(LLMClient):
    provider = Provider.anthropic

    def __init__(self, payload):
        super().__init__(model="fake-model")
        self.payload = payload
        self.prompt: str | None = None

    def _complete(self, *, system, prompt, max_tokens):  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, *, prompt, label=None, **kwargs):
        self.prompt = prompt
        return self.payload, LLMResponse(
            text="{}", provider=self.provider, model=self.model,
            input_tokens=1, output_tokens=1,
        )


def selection(profile, **overrides) -> dict:
    first_role = profile.roles.roles[0]
    data = {
        "tagline": "Engineering Leader  ·  Co-Founder",
        "profile_paragraphs": ["First paragraph.", "Second paragraph."],
        "highlights": [
            {
                "label": "AI in production",
                "text": first_role.bullets[0].text,
                "source_ref": f"{first_role.id}.0",
            }
        ],
        "skill_categories": list(profile.roles.skills)[:2],
        "roles": [{"role_id": first_role.id, "bullet_refs": [f"{first_role.id}.0"]}],
        "earlier_career_ids": [e.id for e in profile.roles.earlier_career][:1],
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- #
# Dates — the age-signal policy's mechanical half
# --------------------------------------------------------------------------- #


def test_dates_render_as_years_only() -> None:
    assert format_dates("2025-06", "2026-01", today=date(2026, 9, 1)) == "2025 – 2026"


def test_the_current_role_reads_as_present() -> None:
    assert format_dates("2026-02", "present", today=date(2026, 9, 1)) == "2026 – Present"


def test_a_role_inside_one_year_shows_that_year_once() -> None:
    assert format_dates("2022-06", "2022-12", today=date(2026, 9, 1)) == "2022"


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #


def test_the_catalogue_keys_every_bullet_by_entry_and_index(profile) -> None:
    catalogue = build_catalogue(profile)
    first = profile.roles.roles[0]

    assert catalogue[f"{first.id}.0"] == first.bullets[0].text


def test_scorer_only_entries_are_absent_from_the_catalogue(profile) -> None:
    """They inform the decision and are never rendered, so the model that
    selects content is never shown them."""
    from jobagent.core.models import Visibility

    hidden = [
        entry.id
        for entry in profile.roles.ai_capability
        if entry.visibility is Visibility.scorer_only
    ]
    catalogue = build_catalogue(profile)

    for entry_id in hidden:
        assert not any(ref.startswith(f"{entry_id}.") for ref in catalogue)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def test_bullet_text_is_copied_verbatim_from_the_profile(profile, jd, assessment) -> None:
    first = profile.roles.roles[0]
    client = FakeClient(selection(profile))

    built = build_resume(jd, profile, assessment, client=client, today=date(2026, 9, 1))

    assert built.content.roles[0].bullets == [first.bullets[0].text]


def test_an_invented_bullet_reference_is_caught(profile, jd, assessment) -> None:
    first = profile.roles.roles[0]
    client = FakeClient(
        selection(profile, roles=[{"role_id": first.id, "bullet_refs": ["made.up.7"]}])
    )

    built = build_resume(jd, profile, assessment, client=client, today=date(2026, 9, 1))

    assert any(issue.rule == "unknown reference" for issue in built.issues)
    assert built.content.roles[0].bullets == []


def test_an_invented_role_id_is_caught(profile, jd, assessment) -> None:
    client = FakeClient(
        selection(profile, roles=[{"role_id": "nonexistent", "bullet_refs": []}])
    )

    built = build_resume(jd, profile, assessment, client=client, today=date(2026, 9, 1))

    assert any(issue.rule == "unknown reference" for issue in built.issues)
    assert built.content.roles == []


def test_an_invented_number_in_the_profile_paragraphs_is_caught(
    profile, jd, assessment
) -> None:
    client = FakeClient(
        selection(profile, profile_paragraphs=["Led 4711 engineers.", "Second."])
    )

    built = build_resume(jd, profile, assessment, client=client, today=date(2026, 9, 1))

    assert any(issue.rule == "unsupported number" for issue in built.issues)


def test_a_malformed_selection_is_an_error(profile, jd, assessment) -> None:
    with pytest.raises(GenerateError, match="did not match the contract"):
        build_resume(jd, profile, assessment, client=FakeClient({"tagline": 12}),
                     today=date(2026, 9, 1))


def test_education_puts_certifications_first(profile, jd, assessment) -> None:
    client = FakeClient(selection(profile))

    built = build_resume(jd, profile, assessment, client=client, today=date(2026, 9, 1))

    certs = [c.name for c in profile.roles.person.certifications]
    if certs:
        assert built.content.education[0].startswith(certs[0])


def test_the_prompt_carries_the_catalogue_and_the_assessment(
    profile, jd, assessment
) -> None:
    client = FakeClient(selection(profile))

    build_resume(jd, profile, assessment, client=client, today=date(2026, 9, 1))

    assert profile.roles.roles[0].id in client.prompt
    assert "Engineering Manager" in client.prompt
    assert "target_role_match" in client.prompt


# --------------------------------------------------------------------------- #
# Regeneration — CLAUDE.md hard rule 4
# --------------------------------------------------------------------------- #


class ScriptedTextClient(LLMClient):
    """Returns queued completions, recording every prompt it was given."""

    provider = Provider.anthropic

    def __init__(self, texts):
        super().__init__(model="fake-model")
        self.texts = list(texts)
        self.prompts: list[str] = []

    def _complete(self, *, system, prompt, max_tokens):
        self.prompts.append(prompt)
        return LLMResponse(
            text=self.texts.pop(0), provider=self.provider, model=self.model,
            input_tokens=1, output_tokens=1,
        )


def test_a_draft_with_a_banned_phrase_is_regenerated(profile, jd, assessment) -> None:
    from jobagent.core.generate import build_cover_letter

    client = ScriptedTextClient(
        [
            "I am thrilled to apply for this role.",
            "I led the team that rebuilt the payments platform.",
        ]
    )

    letter = build_cover_letter(jd, profile, assessment, client=client)

    assert len(client.prompts) == 2
    assert letter.text == "I led the team that rebuilt the payments platform."
    assert letter.issues == []


def test_the_retry_names_the_specific_failure(profile, jd, assessment) -> None:
    """"358 words against a 350-word limit" is actionable; "too long" is not."""
    from jobagent.core.generate import build_cover_letter

    client = ScriptedTextClient(["word " * 400, "A clean second draft."])

    build_cover_letter(jd, profile, assessment, client=client)

    assert "previous draft was rejected" in client.prompts[1]
    assert "350-word limit" in client.prompts[1]


def test_a_draft_that_fails_twice_is_returned_with_its_issues(
    profile, jd, assessment
) -> None:
    """Alan sees the problem either way — silence would be worse than a
    flagged draft."""
    from jobagent.core.generate import build_cover_letter

    client = ScriptedTextClient(["I am thrilled again.", "I am thrilled once more."])

    letter = build_cover_letter(jd, profile, assessment, client=client)

    assert len(client.prompts) == 2
    assert any(issue.rule == "banned phrase" for issue in letter.issues)


def test_a_clean_first_draft_is_not_regenerated(profile, jd, assessment) -> None:
    from jobagent.core.generate import build_cover_letter

    client = ScriptedTextClient(["I led the team that rebuilt the platform."])

    build_cover_letter(jd, profile, assessment, client=client)

    assert len(client.prompts) == 1
