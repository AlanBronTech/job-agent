"""Unit tests for the provider-agnostic LLM adapter.

No network: base-class behaviour is exercised through a fake client, and the
real Anthropic/Gemini SDKs are never imported (lazy imports live inside
``_complete``, which the fake overrides)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobagent.adapters import llm as llm_module
from jobagent.adapters.llm import (
    RETRY_ATTEMPTS,
    RETRY_BASE_DELAY,
    AnthropicClient,
    CallType,
    GeminiClient,
    LLMClient,
    LLMError,
    LLMResponse,
    Provider,
    RetryableLLMError,
    estimate_cost,
    get_client,
    resolve_route,
)
from jobagent.config import Config


def make_config(**overrides) -> Config:
    """A Config isolated from the machine's .env and environment for the routing
    fields, so tests are deterministic regardless of the local shell."""
    base = dict(
        llm_default=None,
        llm_triage=None,
        llm_parse=None,
        llm_score=None,
        llm_generate=None,
        llm_prep=None,
        anthropic_model=None,
        anthropic_triage_model=None,
        anthropic_api_key="key-a",
        gemini_api_key="key-g",
    )
    base.update(overrides)
    return Config(_env_file=None, **base)


class FakeClient(LLMClient):
    """Records prompts and returns queued responses without any SDK."""

    provider = Provider.anthropic

    def __init__(self, responses, model="fake-model", **kwargs):
        super().__init__(model=model, **kwargs)
        self._responses = list(responses)
        self.prompts: list[str] = []

    def _complete(self, *, system, prompt, max_tokens):
        self.prompts.append(prompt)
        return LLMResponse(
            text=self._responses.pop(0),
            provider=self.provider,
            model=self.model,
            input_tokens=100,
            output_tokens=50,
        )


# --------------------------------------------------------------------------- #
# JSON parsing helpers
# --------------------------------------------------------------------------- #


def test_complete_json_plain():
    client = FakeClient(['{"a": 1, "b": "x"}'])
    parsed, response = client.complete_json(prompt="give me json")
    assert parsed == {"a": 1, "b": "x"}
    assert response.text.startswith("{")


def test_complete_json_strips_code_fence():
    client = FakeClient(['```json\n{"a": 1}\n```'])
    parsed, _ = client.complete_json(prompt="give me json")
    assert parsed == {"a": 1}


def test_complete_json_retries_once_with_error_fed_back():
    client = FakeClient(["not json at all", '{"ok": true}'])
    parsed, _ = client.complete_json(prompt="give me json")
    assert parsed == {"ok": True}
    # Two attempts made; the retry prompt names the parse failure.
    assert len(client.prompts) == 2
    assert "could not be parsed" in client.prompts[1]


def test_complete_json_raises_after_exhausting_retries():
    client = FakeClient(["nope", "still nope"])
    with pytest.raises(LLMError, match="did not return valid JSON"):
        client.complete_json(prompt="give me json", retries=1)


# --------------------------------------------------------------------------- #
# complete(): cost + logging
# --------------------------------------------------------------------------- #


def test_complete_sets_label_and_cost():
    client = FakeClient(["hello"], model="claude-haiku-4-5")
    response = client.complete(prompt="hi", label="triage_lead")
    assert response.label == "triage_lead"
    # haiku: $1/1M in, $5/1M out -> 100*1 + 50*5 = 350 / 1e6
    assert response.cost_usd == pytest.approx(350 / 1_000_000)


def test_complete_logs_run_line(tmp_path: Path):
    log = tmp_path / "runs.jsonl"
    client = FakeClient(["a", "b"], model="claude-haiku-4-5", runs_log_path=log)
    client.complete(prompt="one", label="first")
    client.complete(prompt="two", label="second")

    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record["label"] == "first"
    assert record["provider"] == "anthropic"
    assert record["model"] == "claude-haiku-4-5"
    assert record["input_tokens"] == 100
    assert record["cost_usd"] == pytest.approx(350 / 1_000_000)


def test_no_log_path_is_a_noop():
    client = FakeClient(["a"])  # runs_log_path defaults to None
    # Must not raise.
    assert client.complete(prompt="x").text == "a"


# --------------------------------------------------------------------------- #
# Cost estimation
# --------------------------------------------------------------------------- #


def test_estimate_cost_known_model():
    # sonnet: $3/1M in, $15/1M out
    assert estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_estimate_cost_matches_dated_snapshot():
    assert estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 0) == pytest.approx(1.0)


def test_estimate_cost_unknown_model_is_none():
    assert estimate_cost("some-unknown-model", 100, 100) is None


# --------------------------------------------------------------------------- #
# Route resolution
# --------------------------------------------------------------------------- #


def test_route_per_call_overrides_default():
    config = make_config(
        llm_default="anthropic:claude-sonnet-4-6",
        llm_triage="gemini:gemini-2.5-flash",
    )
    route = resolve_route(config, CallType.triage)
    assert route.provider is Provider.gemini
    assert route.model == "gemini-2.5-flash"


def test_route_falls_back_to_default():
    config = make_config(llm_default="anthropic:claude-sonnet-4-6")
    route = resolve_route(config, CallType.score)
    assert route.provider is Provider.anthropic
    assert route.model == "claude-sonnet-4-6"


def test_route_legacy_anthropic_fallback():
    config = make_config(
        anthropic_model="claude-sonnet-4-6",
        anthropic_triage_model="claude-haiku-4-5",
    )
    assert resolve_route(config, CallType.score).model == "claude-sonnet-4-6"
    triage = resolve_route(config, CallType.triage)
    assert triage.model == "claude-haiku-4-5"
    assert triage.provider is Provider.anthropic


def test_route_unknown_provider_raises():
    config = make_config(llm_default="openai:gpt-4")
    with pytest.raises(LLMError, match="Unknown provider"):
        resolve_route(config, CallType.score)


def test_route_missing_colon_raises():
    config = make_config(llm_default="claude-sonnet-4-6")
    with pytest.raises(LLMError, match="expected 'provider:model'"):
        resolve_route(config, CallType.score)


def test_route_nothing_configured_raises():
    config = make_config()
    with pytest.raises(LLMError, match="No model configured"):
        resolve_route(config, CallType.generate)


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def test_get_client_builds_provider_specific_client():
    config = make_config(
        llm_score="anthropic:claude-sonnet-4-6",
        llm_prep="gemini:gemini-2.5-flash",
    )
    score_client = get_client(CallType.score, config)
    prep_client = get_client(CallType.prep, config)

    assert isinstance(score_client, AnthropicClient)
    assert score_client.model == "claude-sonnet-4-6"
    assert score_client._api_key == "key-a"

    assert isinstance(prep_client, GeminiClient)
    assert prep_client.model == "gemini-2.5-flash"
    assert prep_client._api_key == "key-g"


# --------------------------------------------------------------------------- #
# Retry on transient provider failures
#
# Gemini 2.5 Flash returned sustained 503s mid-batch on 2026-08-31. Without
# retry, one overloaded response loses whatever ad was being parsed.
# --------------------------------------------------------------------------- #


class FlakyClient(LLMClient):
    """Fails with the given exceptions, then succeeds."""

    provider = Provider.anthropic

    def __init__(self, failures):
        super().__init__(model="fake-model")
        self._failures = list(failures)
        self.attempts = 0

    def _complete(self, *, system, prompt, max_tokens):
        self.attempts += 1
        if self._failures:
            raise self._failures.pop(0)
        return LLMResponse(
            text="ok",
            provider=self.provider,
            model=self.model,
            input_tokens=1,
            output_tokens=1,
        )


@pytest.fixture
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(llm_module.time, "sleep", slept.append)
    return slept


def test_transient_failure_is_retried_until_it_succeeds(no_sleep) -> None:
    client = FlakyClient([RetryableLLMError("503"), RetryableLLMError("503")])

    assert client.complete(prompt="hi").text == "ok"
    assert client.attempts == 3


def test_backoff_grows_between_attempts(no_sleep) -> None:
    client = FlakyClient([RetryableLLMError("503")] * 2)
    client.complete(prompt="hi")

    assert no_sleep == [RETRY_BASE_DELAY, RETRY_BASE_DELAY * 2]


def test_retries_are_bounded(no_sleep) -> None:
    client = FlakyClient([RetryableLLMError("503")] * 99)

    with pytest.raises(RetryableLLMError):
        client.complete(prompt="hi")
    assert client.attempts == RETRY_ATTEMPTS


def test_permanent_failure_is_not_retried(no_sleep) -> None:
    # A bad key or malformed request must fail immediately, not four times.
    client = FlakyClient([LLMError("401 unauthorized")])

    with pytest.raises(LLMError, match="401"):
        client.complete(prompt="hi")
    assert client.attempts == 1
    assert no_sleep == []


def test_retryable_error_is_an_llm_error() -> None:
    # Callers catching LLMError must still catch the transient subclass.
    assert issubclass(RetryableLLMError, LLMError)
