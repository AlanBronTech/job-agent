"""SC-002: every letter sentence cites existing evidence; the paid claim check."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jobagent.adapters.llm import LLMError, RunContext
from jobagent.config import Config
from jobagent.core.generate import Sentence, build_cover_letter, known_citations
from jobagent.core.profile import load_profile
from jobagent.core.validation import check_citations
from jobagent.services import checks
from tests.quality_seed import PEOPLE, RoutedClient, northwind, northwind_assessment

CONFIG = Config(_env_file=None, llm_default="anthropic:claude-sonnet-5")
CTX = RunContext(command="generate")


@pytest.fixture
def profile(example_dir):
    return load_profile(example_dir)


def para(*sentences):
    return [Sentence(text=t, cites=c) for t, c in sentences]


def test_uncited_and_unknown_block_and_ad_framing_passes(profile):
    known = known_citations(profile)
    issues = check_citations([para(
        ("The role leads a team of eight.", ["ad"]),
        ("I recruited nine people.", ["recent_manager.0"]),
        ("I told the scope story.", ["scope_disagreement"]),
        ("I am a strong communicator.", []),
        ("I ran the freight platform.", ["freight_platform.0"]),
    )], known)
    assert [(i.rule, i.excerpt) for i in issues] == [
        ("uncited claim", "I am a strong communicator."),
        ("unknown citation", "I ran the freight platform."),
    ]


def test_excluded_evidence_is_not_citable(profile):
    known = known_citations(profile, {"underperformer", "recent_manager.3"})
    assert "underperformer" not in known and "recent_manager.3" not in known
    assert "recent_manager.0" in known and "employment_gap" in known


def letter(*sentences):
    return {"paragraphs": [[{"text": t, "cites": c} for t, c in sentences]]}


def test_a_letter_with_an_invented_id_is_regenerated_once(profile):
    client = RoutedClient({"generate_cover_letter": [
        letter(("I ran the freight platform.", ["freight_platform.0"])),
        letter(("I recruited and onboarded nine people.", ["recent_manager.0"])),
    ]})
    built = build_cover_letter(northwind(), profile, northwind_assessment(), client=client, kind=PEOPLE)
    assert len(client.prompts["generate_cover_letter"]) == 2
    assert "unknown citation" in client.prompts["generate_cover_letter"][1]
    assert built.issues == [] and built.text == "I recruited and onboarded nine people."
    assert built.sentences[0].cites == ["recent_manager.0"]


def test_the_claim_check_sees_the_evidence_not_the_scorer_notes(profile):
    sentences = [Sentence(text="After the acquisition I led the integration.", cites=["scope_disagreement"]),
                 Sentence(text="You build route planning.", cites=["ad"])]
    block = checks.claims_block(sentences, profile)
    assert "After the acquisition" in block and "Argued for a narrower first release" in block
    assert "route planning" not in block  # ad framing is not sent
    assert "Reliable anchor for disagree-and-commit" not in block  # a note_for_scorer


def test_the_seeded_acquisition_is_reported(profile):
    """The profile holds no acquisition; the (mocked) checker says so, and it blocks."""
    sentences = [Sentence(text="After the acquisition I led the integration.", cites=["scope_disagreement"])]
    client = RoutedClient({"check_claims": {"mismatches": [
        {"sentence": sentences[0].text, "problem": "unsupported detail: no acquisition in the evidence"}]}})
    result = checks.check_claims(CONFIG, CTX, sentences, profile, client_factory=lambda: client)
    assert result[0].problem.startswith("unsupported detail")
    from jobagent.services.documents import claim_issues
    assert claim_issues(result)[0].rule == "claim mismatch"
    assert claim_issues(result)[0].severity.value == "blocker"


def test_a_failed_check_is_not_checked_never_an_error(profile):
    sentences = [Sentence(text="I recruited nine people.", cites=["recent_manager.0"])]
    down = RoutedClient({"check_claims": LLMError("timed out")})
    assert isinstance(checks.check_claims(CONFIG, CTX, sentences, profile, client_factory=lambda: down),
                      checks.NotChecked)
    garbled = RoutedClient({"check_claims": {"mismatches": [{"nope": 1}]}})
    assert isinstance(checks.check_claims(CONFIG, CTX, sentences, profile, client_factory=lambda: garbled),
                      checks.NotChecked)


def test_nothing_cited_means_nothing_to_pay_for(profile):
    def refuse():
        raise AssertionError("no claim to check, so no call")
    assert checks.check_claims(CONFIG, CTX, [Sentence(text="You build things.", cites=["ad"])],
                               profile, client_factory=refuse) == []


# -- REVIEW-2026-10-16 D1: invented mechanism, sequence and cause --------------------

REPLATFORM = ("Re-platformed the product incrementally over two years, no big-bang cutover, "
              "introducing CI/CD and automated testing while migrating.")
MECHANISM = ("I ran the legacy and new stacks side by side and migrated incrementally, keeping "
             "any single step reversible, and put CI/CD in place before the migration started.")


def test_the_claim_check_is_told_to_judge_mechanism_sequence_and_cause(profile):
    """The fixture: re-platform evidence that says *while*, a sentence that says
    *before* and adds two mechanisms. The prompt must name all three as
    mismatches and carry the worked example; the model's verdict must block."""
    from jobagent.services.documents import claim_issues

    sentence = Sentence(text=MECHANISM, cites=["payments_lead.1"])
    client = RoutedClient({"check_claims": {"mismatches": [
        {"sentence": MECHANISM, "problem": "invented sequence: evidence says while migrating, not before"}]}})
    original = checks.evidence_text
    try:
        checks.evidence_text = lambda p, ref: REPLATFORM  # the fixture's evidence
        result = checks.check_claims(CONFIG, CTX, [sentence], profile, client_factory=lambda: client)
    finally:
        checks.evidence_text = original
    prompt = client.prompts["check_claims"][0]
    assert "mechanism, sequence or cause" in prompt.lower()
    assert "side by side" in prompt and "before contradicts *while*" in prompt.replace("*before*", "before")
    assert REPLATFORM in prompt and MECHANISM in prompt
    blockers = claim_issues(result)
    assert [(b.rule, b.severity.value) for b in blockers] == [("claim mismatch", "blocker")]


def test_a_letter_sentence_with_no_citation_is_still_a_blocker(profile):
    """D1's first requirement was already in force (spec 003); kept as a regression."""
    issues = check_citations([para(("I ran both stacks side by side.", []))], known_citations(profile))
    assert [(i.rule, i.severity.value) for i in issues] == [("uncited claim", "blocker")]


# -- REVIEW-2026-10-16 D2: one sentence, two roles' facts ----------------------------


def test_a_sentence_naming_an_employer_its_evidence_is_not_from_blocks(profile):
    """Attributes from entry A (an incident-management bullet at one employer)
    attached to the employer of entry B. The paid check caught it on JD 85; this
    makes it a code check that cannot miss."""
    from jobagent.core.validation import check_employers

    merged = Sentence(text="At Example Manufacturing Co I owned incident management for the offshore team.",
                      cites=["startup_em.0"])
    issues = check_employers([[merged]], profile)
    assert [(i.rule, i.severity.value) for i in issues] == [("employer not in cited evidence", "blocker")]
    assert "Example Manufacturing Co" in issues[0].detail


def test_naming_the_employer_of_the_cited_evidence_passes(profile):
    from jobagent.core.validation import check_employers

    fine = Sentence(text="At Example Startup I recruited and led a team of 6.", cites=["startup_em.0"])
    story = Sentence(text="At Example Startup I argued for a narrower scope.", cites=["scope_disagreement"])
    framing = Sentence(text="Example Manufacturing Co is where I learned the most.", cites=["ad"])
    assert check_employers([[fine, story]], profile) == []
    assert check_employers([[framing]], profile)  # "ad" licenses no employer of Alan's


def test_the_letter_is_rewritten_when_it_merges_two_employers(profile):
    merged = {"paragraphs": [[{"text": "At Example Manufacturing Co I owned the offshore team's incidents.",
                               "cites": ["startup_em.0"]}]]}
    fixed = {"paragraphs": [[{"text": "At Example Startup I recruited and led a team of 6.",
                              "cites": ["startup_em.0"]}]]}
    client = RoutedClient({"generate_cover_letter": [merged, fixed]})
    built = build_cover_letter(northwind(), profile, northwind_assessment(), client=client, kind=PEOPLE)
    assert "employer not in cited evidence" in client.prompts["generate_cover_letter"][1]
    assert built.issues == []


def test_a_story_cited_by_a_step_counts_as_the_story(profile_factory) -> None:
    """`story_id.0` is a sequence step of a story, not an unknown id (2026-10-22)."""
    from jobagent.core.generate import Sentence, _story_cites, known_citations
    from jobagent.core.profile import load_profile

    profile = load_profile(profile_factory())
    story = profile.stories.stories[0].id
    known = known_citations(profile)
    fixed = _story_cites([[Sentence(text="x", cites=[f"{story}.0", "ad", "made_up.1"])]], profile, known)
    assert fixed[0][0].cites == [story, "ad", "made_up.1"]


def test_an_explanation_licenses_the_employers_it_names(profile):
    """The Java explanation lists Macquarie Bank; citing it may name Macquarie (2026-10-22)."""
    from jobagent.core.validation import check_employers

    profile.stories.explanations.stack_mismatch = "Java at Example Manufacturing Co and elsewhere."
    sentence = Sentence(text="I wrote Java at Example Manufacturing Co.", cites=["stack_mismatch"])
    assert check_employers([[sentence]], profile) == []


def test_a_highlight_citing_several_bullets_of_one_entry_cites_the_entry() -> None:
    """JD 89: ["datallama.0", "datallama.1"] lost a whole resume on a type error."""
    from jobagent.core.generate import _Highlight

    assert _Highlight(label="x", text="y", source_ref=["venture.0", "venture.1"]).source_ref == "venture"
    assert _Highlight(label="x", text="y", source_ref=["a.0", "b.1"]).source_ref == "a.0"
    assert _Highlight(label="x", text="y", source_ref=["a.0"]).source_ref == "a.0"
