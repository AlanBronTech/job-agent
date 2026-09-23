"""A call that produced nothing still has to leave a record.

On 2026-09-23 a `jd add` died with `httpx.ReadTimeout` raised out of the stream
while the model was still generating. Two things were wrong at once:

* `except anthropic.APIError` does not catch a transport exception, so the
  retry wrapper that exists for exactly this never saw it and the command died
  on an unhandled traceback. A plain re-run succeeded immediately.
* The run log was written on success only, so the attempt left no trace. The
  tokens were generated and billed, and `jobagent spend` was silently low by
  that amount — "no record" and "the call never happened" looked identical.

That is the `price_unknown` lesson one layer earlier: a cost nobody can see is
worse than a cost that is wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from jobagent.adapters import llm as llm_module
from jobagent.adapters.llm import (
    RETRY_ATTEMPTS,
    AnthropicClient,
    LLMClient,
    LLMError,
    LLMResponse,
    Provider,
    QuotaExhaustedError,
    RetryableLLMError,
    RunContext,
    _is_transport_failure,
)
from jobagent.core.spend import build_report


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm_module.time, "sleep", lambda _: None)


class Client(LLMClient):
    """Raises the given exceptions in order, then succeeds."""

    provider = Provider.anthropic

    def __init__(self, failures, *, log: Path, context: RunContext | None = None):
        super().__init__(
            model="claude-sonnet-5",
            runs_log_path=log,
            context=context or RunContext(command="jd add", source="cli", run_id="r1"),
        )
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
            input_tokens=4962,
            output_tokens=2100,
        )


def records(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]


@pytest.fixture
def log(tmp_path) -> Path:
    return tmp_path / "runs.jsonl"


# --------------------------------------------------------------------------- #
# Classifying the failure
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("the read operation timed out"),
        httpx.ConnectTimeout("connect timed out"),
        httpx.ConnectError("refused"),
        httpx.RemoteProtocolError("peer closed"),
    ],
)
def test_transport_failures_are_recognised(exc) -> None:
    """Every one of these descends from `httpx.TransportError`."""
    assert _is_transport_failure(exc) is True


@pytest.mark.parametrize("exc", [ValueError("nope"), KeyError("k"), LLMError("401")])
def test_other_exceptions_are_not_transport_failures(exc) -> None:
    assert _is_transport_failure(exc) is False


def test_a_transport_failure_is_retried_rather_than_crashing(no_sleep, log) -> None:
    """The actual 2026-09-23 failure, which used to escape as a traceback."""
    client = Client([httpx.ReadTimeout("timed out")] * 2, log=log)

    assert client.complete(prompt="p", label="parse_jd").text == "ok"
    assert client.attempts == 3


def test_a_non_transport_exception_is_not_swallowed(no_sleep, log) -> None:
    """The broad `except` must not turn a real bug into a retry."""
    client = Client([ValueError("a genuine bug")], log=log)

    with pytest.raises(ValueError):
        client.complete(prompt="p", label="parse_jd")
    assert client.attempts == 1


# --------------------------------------------------------------------------- #
# The record
# --------------------------------------------------------------------------- #


def test_every_failed_attempt_is_logged_even_when_a_retry_rescues_it(
    no_sleep, log
) -> None:
    """A rescued attempt was still billed for what it generated."""
    client = Client([httpx.ReadTimeout("timed out")] * 2, log=log)
    client.complete(prompt="p", label="parse_jd")

    written = records(log)
    assert [r.get("outcome") for r in written] == ["error", "error", "ok"]
    assert [r.get("attempt") for r in written[:2]] == [1, 2]
    assert [r.get("retried") for r in written[:2]] == [True, True]


def test_exhausted_retries_log_every_attempt_and_raise(no_sleep, log) -> None:
    client = Client([httpx.ReadTimeout("timed out")] * 99, log=log)

    with pytest.raises(RetryableLLMError):
        client.complete(prompt="p", label="interview_prep")

    written = records(log)
    assert len(written) == RETRY_ATTEMPTS
    assert all(r["outcome"] == "error" for r in written)
    # The last attempt is the one that gave up.
    assert written[-1]["retried"] is False


def test_the_failure_record_carries_the_attribution_fields(no_sleep, log) -> None:
    """Without these, a failure cannot be attributed to a command or an ad."""
    client = Client(
        [httpx.ReadTimeout("timed out")] * 99,
        log=log,
        context=RunContext(command="prep", jd_id=46, source="cli", run_id="def456"),
    )
    with pytest.raises(RetryableLLMError):
        client.complete(prompt="p", label="interview_prep")

    first = records(log)[0]
    assert first["command"] == "prep"
    assert first["jd_id"] == 46
    assert first["source"] == "cli"
    assert first["run_id"] == "def456"
    assert first["label"] == "interview_prep"
    assert first["model"] == "claude-sonnet-5"
    assert "ReadTimeout" in first["error"]


def test_a_failure_does_not_implicate_the_price_table(no_sleep, log) -> None:
    """`price_unknown` means the model has no price. This is a different gap:
    there is no usage to price at all, and `outcome` is what says so."""
    client = Client([httpx.ReadTimeout("timed out")] * 99, log=log)
    with pytest.raises(RetryableLLMError):
        client.complete(prompt="p", label="parse_jd")

    first = records(log)[0]
    assert first["cost_usd"] is None
    assert first["price_unknown"] is False
    assert first["input_tokens"] is None
    assert first["output_tokens"] is None


def test_a_terminal_error_is_logged_once_and_not_retried(no_sleep, log) -> None:
    client = Client([LLMError("401 unauthorised")], log=log)

    with pytest.raises(LLMError):
        client.complete(prompt="p", label="parse_jd")

    written = records(log)
    assert len(written) == 1
    assert written[0]["outcome"] == "error"
    assert written[0]["retried"] is False
    assert client.attempts == 1


def test_an_exhausted_quota_is_logged_and_not_retried(no_sleep, log) -> None:
    """Backing off cannot clear a daily cap, but it still produced nothing."""
    client = Client([QuotaExhaustedError("free tier used up")], log=log)

    with pytest.raises(QuotaExhaustedError):
        client.complete(prompt="p", label="parse_jd")

    assert client.attempts == 1
    assert records(log)[0]["outcome"] == "error"


def test_a_successful_call_records_its_outcome(no_sleep, log) -> None:
    Client([], log=log).complete(prompt="p", label="parse_jd")

    assert records(log)[0]["outcome"] == "ok"


def test_logging_without_a_log_path_is_harmless(no_sleep) -> None:
    class Unlogged(Client):
        def __init__(self):
            LLMClient.__init__(self, model="claude-sonnet-5")
            self._failures = [httpx.ReadTimeout("timed out")] * 99
            self.attempts = 0

    with pytest.raises(RetryableLLMError):
        Unlogged().complete(prompt="p", label="parse_jd")


# --------------------------------------------------------------------------- #
# What `spend` does with it
# --------------------------------------------------------------------------- #


def test_spend_holds_failures_apart_from_the_total(no_sleep, log) -> None:
    client = Client([httpx.ReadTimeout("timed out")] * 2, log=log)
    client.complete(prompt="p", label="parse_jd")

    report = build_report(records(log), price_lookup=lambda _: (2e-6, 10e-6))

    # One real call, two attempts that produced nothing.
    assert report.calls == 1
    assert report.failed_calls == 2
    assert report.total_usd > 0
    # A failure is not a pricing gap.
    assert report.unpriced_calls == 0


def test_records_without_an_outcome_field_count_as_successes() -> None:
    """Every record written before failures were logged predates the field.

    Reading those as failures would rewrite the whole history as broken.
    """
    legacy = [
        {"ts": 1.0, "label": "parse_jd", "model": "claude-sonnet-5", "cost_usd": 0.03},
        {"ts": 2.0, "label": "score_fit", "model": "claude-sonnet-5", "cost_usd": 0.11},
    ]

    report = build_report(legacy)

    assert report.calls == 2
    assert report.failed_calls == 0
    assert report.total_usd == pytest.approx(0.14)


def test_a_log_of_only_failures_reports_no_spend_but_names_them() -> None:
    failures = [
        {"ts": 1.0, "label": "parse_jd", "model": "claude-sonnet-5",
         "cost_usd": None, "outcome": "error", "error": "ReadTimeout: x"},
    ]

    report = build_report(failures)

    assert report.calls == 0
    assert report.failed_calls == 1
    assert report.total_usd == 0.0


def test_the_anthropic_client_wraps_a_transport_failure(no_sleep, tmp_path) -> None:
    """The provider handler, independently of the loop's safety net."""
    client = AnthropicClient(model="claude-sonnet-5", api_key="k")

    def boom(**_):
        raise httpx.ReadTimeout("timed out")

    client._sdk = lambda: type(
        "S", (), {"messages": type("M", (), {"stream": staticmethod(boom)})()}
    )()

    with pytest.raises(RetryableLLMError):
        client._complete(system=None, prompt="p", max_tokens=10)
