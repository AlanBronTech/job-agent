"""Interview prep, and what it does with a model that volunteers a field.

`core/prep.py` had no tests. It got some the day a real prep run died: the
model returned an `answer_outline_note` the prompt never asked for, the models
set ``extra="forbid"``, and the whole run failed *after* the questions had been
written and paid for. Alan was preparing for an interview at the time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from jobagent.adapters.llm import LLMResponse, Provider
from jobagent.core.models import (
    FitAssessment,
    JobDescription,
    Verdict,
    WorkArrangement,
    WorkType,
)
from jobagent.core.prep import PrepError, prepare
from jobagent.core.profile import load_profile

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


class StubClient:
    """Returns one canned JSON payload. No SDK, no network."""

    provider = Provider.anthropic
    model = "claude-sonnet-5"

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def complete_json(self, *, prompt, label=None, max_tokens=None, retries=1):
        return self._payload, LLMResponse(
            text=json.dumps(self._payload),
            provider=self.provider,
            model=self.model,
            input_tokens=10,
            output_tokens=10,
        )


@pytest.fixture
def profile(profile_factory):
    return load_profile(profile_factory())


@pytest.fixture
def jd() -> JobDescription:
    return JobDescription(
        title="AI Engineer",
        company="Upgrowth",
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        raw_text="Drive the rollout of an Agentic Delivery Lifecycle. " * 20,
        ingested_at=NOW,
    )


@pytest.fixture
def assessment() -> FitAssessment:
    return FitAssessment(
        jd_id=46,
        overall_score=46,
        recruiter_screen_score=22,
        verdict=Verdict.apply_with_caveats,
        rationale="Scope fits the AI adoption evidence; SDD is not evidenced.",
        target_role_match=True,
        target_role_note="Closest fit is AI Adoption / AI Enablement Lead.",
        questions_to_ask=["Who is the actual employer?"],
        scored_at=NOW,
    )


def payload(**overrides) -> dict:
    data = {
        "opening": "Thirty seconds on the agentic delivery work.",
        "questions": [
            {
                "question": "What is your direct experience with SDD?",
                "why_asked": "The ad leads with it and the profile does not.",
                "story_ref": None,
                "answer_outline": "Name the gap, then the adjacent agent work.",
                "hard": True,
            }
        ],
        "questions_to_ask": ["Is this permanent or contract?"],
    }
    data.update(overrides)
    return data


def test_prep_is_produced_from_a_well_formed_answer(jd, profile, assessment) -> None:
    prep, issues = prepare(
        jd, profile, assessment, client=StubClient(payload()), prepared_at=NOW
    )

    assert [q.question for q in prep.questions] == [
        "What is your direct experience with SDD?"
    ]
    assert not [i for i in issues if i.rule == "unknown reference"]


def test_a_volunteered_field_does_not_fail_the_run(jd, profile, assessment) -> None:
    """The live failure. `extra="forbid"` turned one stray key into a total
    loss of work already paid for, so unknown keys are dropped the way
    `jd.py` has always dropped them from the parser's output."""
    question = payload()["questions"][0] | {
        "answer_outline_note": "Keep it to ninety seconds.",
        "confidence": 0.8,
    }

    prep, _ = prepare(
        jd,
        profile,
        assessment,
        client=StubClient(payload(questions=[question])),
        prepared_at=NOW,
    )

    assert prep.questions[0].question == "What is your direct experience with SDD?"
    assert prep.questions[0].answer_outline == "Name the gap, then the adjacent agent work."


def test_the_contract_is_read_off_the_model_not_hand_listed() -> None:
    """A hand-written copy of a model's fields drifts from it. That is how the
    number haystack in `validation.py` came to be missing four of them."""
    from jobagent.core.models import PrepQuestion
    from jobagent.core.prep import _QUESTION_KEYS

    assert _QUESTION_KEYS == frozenset(PrepQuestion.model_fields)


def test_a_missing_required_field_is_still_an_error(jd, profile, assessment) -> None:
    """Dropping unknown keys must not become tolerating a broken contract."""
    broken = {k: v for k, v in payload()["questions"][0].items() if k != "question"}

    with pytest.raises(PrepError, match="did not match the contract"):
        prepare(
            jd,
            profile,
            assessment,
            client=StubClient(payload(questions=[broken])),
            prepared_at=NOW,
        )


def test_a_story_that_does_not_exist_is_reported(jd, profile, assessment) -> None:
    """It fired on the real Upgrowth run: the model cited `datallama`, which is
    an entry id, not a story. Answering from a story that does not exist is
    worse than answering without one."""
    question = payload()["questions"][0] | {"story_ref": "not_a_real_story"}

    _, issues = prepare(
        jd,
        profile,
        assessment,
        client=StubClient(payload(questions=[question])),
        prepared_at=NOW,
    )

    assert any(i.rule == "unknown reference" for i in issues)
