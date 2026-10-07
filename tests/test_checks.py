"""SC-004: the independent review sees the ad, the policies and the documents only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jobagent.adapters.llm import LLMError, RunContext
from jobagent.config import Config
from jobagent.core.profile import load_profile
from jobagent.core import roles
from jobagent.core.validation import banned_phrases
from jobagent.services import checks
from jobagent.services.documents import is_ready
from tests.quality_seed import (
    ORIGINAL_LETTER,
    ORIGINAL_RESUME,
    PEOPLE,
    RoutedClient,
    northwind,
)

CONFIG = Config(_env_file=None, llm_default="anthropic:claude-sonnet-5")
CTX = RunContext(command="generate")
DOCS = {"resume": ORIGINAL_RESUME, "cover letter": ORIGINAL_LETTER}

# What a reviewer reading the worked example should say; the model is mocked,
# so this proves the plumbing carries all three faults through, not the model.
FAULTS = {"blocking": [
    {"document": "resume", "finding": "Opens on a managed exit for a people-focused role."},
    {"document": "resume", "finding": "One disagree-and-commit story used four times."},
    {"document": "cover letter", "finding": "States an acquisition nothing else supports."},
], "suggestions": [{"document": "cover letter", "finding": "Name the route-planning work."}]}


@pytest.fixture
def profile(example_dir):
    return load_profile(example_dir)


def run_review(profile, payload):
    client = RoutedClient({"review_documents": payload})
    excluded = checks.excluded_descriptions(profile, roles.excluded_ids(profile, PEOPLE.kinds))
    result = checks.review(CONFIG, CTX, northwind(), DOCS, kind=PEOPLE, excluded=excluded,
                           banned=banned_phrases(profile.voice), client_factory=lambda: client)
    return result, client.prompts["review_documents"][0]


def test_the_reviewer_reads_the_ad_policies_and_documents(profile):
    _, prompt = run_review(profile, {"blocking": [], "suggestions": []})
    assert "Coaching and growing engineers" in prompt  # the parsed ad
    assert "The age-signal policy" in prompt and "Standing decisions" in prompt
    assert "managed exit" in prompt and "After the acquisition" in prompt  # the documents
    assert "story: Managing an underperformer" in prompt  # what is excluded, by label
    assert "people-focused" in prompt


def test_the_reviewer_never_sees_the_writer_prompt_or_scorer_notes(profile):
    _, prompt = run_review(profile, {"blocking": [], "suggestions": []})
    assert "You do not write the resume" not in prompt  # generate_resume.md
    assert "Must cover" not in prompt
    assert "Reliable anchor for disagree-and-commit" not in prompt  # a note_for_scorer
    assert "<catalogue>" not in prompt


def test_the_worked_example_faults_come_back_blocking(profile):
    result, _ = run_review(profile, FAULTS)
    assert len(result.blocking) == 3 and len(result.suggestions) == 1
    assert not is_ready([], None, result)
    md = checks.review_markdown(result)
    assert md.startswith("# Review") and "**Not ready.**" in md and "acquisition" in md


def test_a_clean_review_is_ready_and_a_failed_one_is_not_reviewed(profile):
    clean, _ = run_review(profile, {"blocking": [], "suggestions": []})
    assert is_ready([], None, clean)
    failed, _ = run_review(profile, LLMError("timed out"))
    assert isinstance(failed, checks.NotReviewed) and not is_ready([], None, failed)
    assert "Not reviewed: " in checks.review_markdown(failed)
    assert not is_ready([], None, None)  # switched off: never ready


def test_a_blocker_from_the_code_checks_or_a_failed_claim_check_is_not_ready(profile):
    clean, _ = run_review(profile, {"blocking": [], "suggestions": []})
    blocker = SimpleNamespace(severity=SimpleNamespace(value="blocker"))
    assert not is_ready([blocker], None, clean)
    assert not is_ready([], checks.NotChecked("timed out"), clean)
    assert is_ready([], [], clean)
