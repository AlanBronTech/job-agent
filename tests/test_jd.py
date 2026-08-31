"""Unit tests for JD parsing. The LLM is always faked — no network, no cost.

Real JD fixtures belong in tests/fixtures/ and are still outstanding; the text
used here is a minimal stand-in sized to clear the length guard, not a
representative advertisement.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from jobagent.adapters.llm import LLMClient, LLMError, LLMResponse, Provider
from jobagent.core.jd import JDError, parse_jd
from jobagent.core.models import WorkArrangement, WorkType
from jobagent.core.prompts import PROMPTS_DIR, PromptError, load_prompt

SAMPLE_TEXT = (
    "Engineering Manager — Acme Pty Ltd, Sydney CBD. Hybrid, three days in the "
    "office. Permanent role paying $160,000 to $190,000 plus superannuation. "
    "You will lead a team of eight engineers across two squads. Required: "
    "team leadership, PHP, CI/CD. Desirable: AWS exposure."
)

FULL_RESPONSE = {
    "title": "Engineering Manager",
    "company": "Acme Pty Ltd",
    "location": "Sydney CBD",
    "work_type": "permanent",
    "work_arrangement": "hybrid",
    "salary_range": {
        "min_aud": 160000,
        "max_aud": 190000,
        "includes_super": False,
        "raw": "$160,000 to $190,000 plus superannuation",
    },
    "seniority": "Manager",
    "must_haves": ["Team leadership", "PHP", "CI/CD"],
    "nice_to_haves": ["AWS exposure"],
    "tech_stack": ["PHP", "AWS"],
    "responsibilities": ["Lead a team of eight engineers across two squads"],
    "red_flags": [],
}


class FakeClient(LLMClient):
    """Returns canned JSON. Records the prompt so tests can assert on it."""

    provider = Provider.anthropic

    def __init__(self, payload: object = None, *, error: Exception | None = None):
        super().__init__(model="fake-model")
        self._payload = FULL_RESPONSE if payload is None else payload
        self._error = error
        self.prompts: list[str] = []

    def _complete(self, *, system, prompt, max_tokens) -> LLMResponse:
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error
        return LLMResponse(
            text=json.dumps(self._payload),
            provider=self.provider,
            model=self.model,
            input_tokens=100,
            output_tokens=50,
        )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_parses_a_full_response() -> None:
    jd = parse_jd(SAMPLE_TEXT, client=FakeClient(), source="seek")

    assert jd.title == "Engineering Manager"
    assert jd.company == "Acme Pty Ltd"
    assert jd.work_type is WorkType.permanent
    assert jd.work_arrangement is WorkArrangement.hybrid
    assert jd.salary_range.min_aud == 160000
    assert jd.salary_range.includes_super is False
    assert jd.must_haves == ["Team leadership", "PHP", "CI/CD"]
    assert jd.source == "seek"


def test_raw_text_is_preserved_unstripped() -> None:
    padded = "\n\n  " + SAMPLE_TEXT + "  \n"
    jd = parse_jd(padded, client=FakeClient())

    assert jd.raw_text == padded


def test_jd_text_reaches_the_prompt() -> None:
    client = FakeClient()
    parse_jd(SAMPLE_TEXT, client=client)

    assert SAMPLE_TEXT in client.prompts[0]
    assert "{jd_text}" not in client.prompts[0]


def test_ingested_at_defaults_to_now() -> None:
    before = datetime.now(timezone.utc)
    jd = parse_jd(SAMPLE_TEXT, client=FakeClient())

    assert before <= jd.ingested_at <= datetime.now(timezone.utc)


def test_explicit_ingested_at_is_used() -> None:
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert parse_jd(SAMPLE_TEXT, client=FakeClient(), ingested_at=moment).ingested_at == moment


def test_missing_optional_fields_get_defaults() -> None:
    jd = parse_jd(SAMPLE_TEXT, client=FakeClient({"title": "Engineer"}))

    assert jd.company is None
    assert jd.salary_range is None
    assert jd.work_type is WorkType.unknown
    assert jd.work_arrangement is WorkArrangement.unknown
    assert jd.must_haves == []


def test_unexpected_keys_are_dropped_not_fatal() -> None:
    # extra="forbid" on the model would otherwise fail the whole parse because
    # the model volunteered a field nobody asked for.
    payload = dict(FULL_RESPONSE, salary_currency="AUD", confidence=0.9)

    assert parse_jd(SAMPLE_TEXT, client=FakeClient(payload)).title == "Engineering Manager"


# --------------------------------------------------------------------------- #
# Input guards
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_empty_text_is_rejected(text: str) -> None:
    with pytest.raises(JDError, match="No job description text"):
        parse_jd(text, client=FakeClient())


def test_text_too_short_is_rejected_before_spending_a_call() -> None:
    client = FakeClient()

    with pytest.raises(JDError, match="Paste the full advertisement"):
        parse_jd("Engineering Manager, Sydney", client=client)

    assert client.prompts == []


# --------------------------------------------------------------------------- #
# Model misbehaviour
# --------------------------------------------------------------------------- #


def test_llm_error_becomes_jd_error() -> None:
    client = FakeClient(error=LLMError("rate limited"))

    with pytest.raises(JDError, match="rate limited"):
        parse_jd(SAMPLE_TEXT, client=client)


def test_non_object_json_is_rejected() -> None:
    with pytest.raises(JDError, match="Expected a JSON object"):
        parse_jd(SAMPLE_TEXT, client=FakeClient(["a", "list"]))


@pytest.mark.parametrize("title", [None, "", "   "])
def test_missing_title_is_rejected(title) -> None:
    with pytest.raises(JDError, match="no job title"):
        parse_jd(SAMPLE_TEXT, client=FakeClient(dict(FULL_RESPONSE, title=title)))


def test_invalid_enum_value_reports_schema_drift() -> None:
    payload = dict(FULL_RESPONSE, work_type="freelance")

    with pytest.raises(JDError, match="did not match the JobDescription schema"):
        parse_jd(SAMPLE_TEXT, client=FakeClient(payload))


def test_wrong_shaped_salary_reports_schema_drift() -> None:
    payload = dict(FULL_RESPONSE, salary_range="$160k-$190k")

    with pytest.raises(JDError, match="did not match the JobDescription schema"):
        parse_jd(SAMPLE_TEXT, client=FakeClient(payload))


# --------------------------------------------------------------------------- #
# Prompt loading
# --------------------------------------------------------------------------- #


def test_parse_jd_prompt_exists_and_declares_its_placeholder() -> None:
    text = (PROMPTS_DIR / "parse_jd.md").read_text(encoding="utf-8")

    assert "{jd_text}" in text


def test_load_prompt_substitutes_without_touching_json_braces() -> None:
    # str.format would raise on the JSON example in the prompt body.
    rendered = load_prompt("parse_jd", jd_text="PASTED")

    assert "PASTED" in rendered
    assert '"must_haves": ["string"]' in rendered


def test_missing_prompt_raises() -> None:
    with pytest.raises(PromptError, match="No prompt named"):
        load_prompt("no_such_prompt")
