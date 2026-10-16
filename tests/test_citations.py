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
