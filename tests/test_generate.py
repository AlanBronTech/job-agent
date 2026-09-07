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
    _founder_dates,
    _founder_line,
    _unknown,
    build_catalogue,
    build_citable,
    build_resume,
    format_dates,
)
from jobagent.core.models import (
    Bullet,
    FitAssessment,
    FounderEntry,
    JobDescription,
    Verdict,
    Visibility,
    WorkArrangement,
    WorkType,
)
from jobagent.core.profile import load_profile
from jobagent.core.validation import Severity


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


# --------------------------------------------------------------------------- #
# Founder ventures in EARLIER CAREER
# --------------------------------------------------------------------------- #
#
# `founder_track_record` was rendered into the catalogue with referenceable
# bullets but resolved by neither `roles` nor `earlier_career_ids`, so the model
# had no correct slot for it. On the Colonial First State generation it put four
# founder ids in `roles` and lost all four to blockers.
#
# The format below is taken from AlanBronResumeMaster2026.docx, which wins over
# any spec that disagrees with it.


def founder(**overrides) -> FounderEntry:
    data = {
        "id": "home_design_directory",
        "company": "Australian Home Design Directory",
        "role": "Co-founder & CTO",
        "visibility": Visibility.full,
        "start": "2006-09",
        "end": "2016-06",
        "bullets": [Bullet(text="Built it.", tags=["founder"], evidence_strength="strong")],
        "summary": "sole architect; grew it to 1M+ annual visitors.",
    }
    return FounderEntry.model_validate(data | overrides)


def test_a_closed_venture_renders_in_the_masters_format() -> None:
    line, issue = _founder_line(founder())

    assert issue is None
    assert line == (
        "Co-founder & CTO, Australian Home Design Directory (2006–16) — "
        "sole architect; grew it to 1M+ annual visitors."
    )


def test_the_end_year_is_two_digits_like_the_master() -> None:
    """`2006–16`, not `2006 – 2016`. The role headings use the other style."""
    assert _founder_dates("2006-09", "2016-06") == "2006–16"
    assert _founder_dates("2015-07", "2017-06") == "2015–17"


def test_an_undated_venture_renders_without_a_parenthetical() -> None:
    """OneBlink is deliberately undated — Alan's recollection and the master
    disagree and neither is verified, so no date is asserted."""
    line, issue = _founder_line(founder(start=None, end=None))

    assert issue is None
    assert "(" not in line


def test_a_single_year_is_not_rendered_as_a_range() -> None:
    assert _founder_dates("2015-01", "2015-11") == "2015"


def test_an_ongoing_venture_is_kept_out_of_earlier_career() -> None:
    """DataLlama appears in the master exactly once, as a CAREER HIGHLIGHT.
    Its note_for_scorer forbids presenting it as full-time work or using it to
    fill a timeline gap, and it is still running."""
    line, issue = _founder_line(founder(id="datallama", start="2018", end="present"))

    assert line == ""
    assert issue is not None
    assert issue.severity is Severity.blocker
    assert "highlights" in issue.detail.lower()


def test_a_venture_with_no_summary_is_blocked_not_invented() -> None:
    """The model returns references for the resume and never composes
    experience prose, so a missing summary is a profile gap, not a prompt to
    write one."""
    line, issue = _founder_line(founder(summary=None))

    assert line == ""
    assert issue is not None
    assert "roles.yaml" in issue.detail


def test_an_unknown_earlier_career_id_no_longer_claims_invention() -> None:
    """The old wording sent a reader to check whether the profile had changed.
    A real id in the wrong collection looks identical to a fabricated one."""
    issue = _unknown("datallama", "earlier career entry")

    assert "invented" not in issue.detail.split("before assuming")[0]
    assert "another section" in issue.detail


# --------------------------------------------------------------------------- #
# What a highlight may cite, as against what a bullet may copy
# --------------------------------------------------------------------------- #


def test_an_earlier_career_entry_is_citable(profile) -> None:
    """Thirty years of domain evidence lives in `earlier_career`, and the
    selection prompt shows it with a bare id and no bullets. A highlight citing
    one used to blocker as an invented reference — on a superannuation ad, for
    citing the superannuation work."""
    entry = profile.roles.earlier_career[0]

    assert entry.id in build_citable(profile)


def test_an_earlier_career_entry_stays_out_of_the_bullet_catalogue(profile) -> None:
    """The catalogue is what gets copied verbatim into a dated role block. An
    earlier-career summary reaching it would put undated thirty-year-old text
    inside EXPERIENCE, which is the leak this separation exists to prevent."""
    entry = profile.roles.earlier_career[0]

    assert entry.id not in build_catalogue(profile)


def test_an_entry_heading_is_citable_as_well_as_its_bullets(profile) -> None:
    role = profile.roles.roles[0]
    citable = build_citable(profile)

    assert role.id in citable
    assert f"{role.id}.0" in citable


def test_an_invented_id_is_still_not_citable(profile) -> None:
    assert "totally_made_up" not in build_citable(profile)


def test_scorer_only_entries_are_not_citable(profile) -> None:
    """Citing one would put prose derived from never-rendered material on the
    page, which is the thing `scorer_only` exists to stop."""
    from jobagent.core.models import Visibility

    hidden = [
        entry.id
        for entry in profile.roles.ai_capability
        if entry.visibility is Visibility.scorer_only
    ]
    citable = build_citable(profile)

    assert hidden, "the example profile should carry a scorer_only entry"
    for entry_id in hidden:
        assert entry_id not in citable


def test_a_highlight_citing_earlier_career_raises_no_blocker(
    profile, jd, assessment
) -> None:
    """End to end: the Colonial First State case that produced the report."""
    entry = profile.roles.earlier_career[0]
    client = FakeClient(
        selection(
            profile,
            highlights=[
                {
                    "label": "Superannuation domain adjacency",
                    "text": entry.summary,
                    "source_ref": entry.id,
                }
            ],
        )
    )

    built = build_resume(jd, profile, assessment, client=client, today=date(2026, 9, 7))

    blockers = [i for i in built.issues if i.severity is Severity.blocker]
    assert blockers == []


def test_a_highlight_citing_nothing_real_still_blocks(profile, jd, assessment) -> None:
    client = FakeClient(
        selection(
            profile,
            highlights=[
                {
                    "label": "Invented",
                    "text": "Something that is not in the profile.",
                    "source_ref": "no_such_entry",
                }
            ],
        )
    )

    built = build_resume(jd, profile, assessment, client=client, today=date(2026, 9, 7))

    blockers = [i for i in built.issues if i.severity is Severity.blocker]
    assert any("no_such_entry" in (i.excerpt or "") for i in blockers)
