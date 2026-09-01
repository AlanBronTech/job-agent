"""Provider-agnostic LLM access.

Every model call in the app goes through here. Callers pick a *call type*
(triage, JD parsing, scoring, generation, prep); config maps each call type to a
concrete provider + model. Swapping a provider for a given task is a config edit,
never a code change — which is the whole point of the interface.

Two providers are implemented: Anthropic (Claude) and Google Gemini. Adding a
third means one new `LLMClient` subclass and one `Provider` enum value.

Design notes:

* JSON handling and cost logging live in the base class, so they behave
  identically across providers. Structured output is done the portable way —
  instruct JSON-only, parse defensively, retry once feeding the parse error back
  (per CLAUDE.md) — rather than a provider-specific structured-output API.
* No `temperature` / thinking parameters are exposed. Models are selected from
  config and vary across providers and generations; the newest Claude models
  reject sampling params outright, and thinking config is model-specific. Keeping
  the surface minimal means any configured model works without a 400.
* SDKs are imported lazily inside each client, so importing this module — and
  constructing a client — needs neither package installed nor a network call.
  That keeps unit tests fast and mock-friendly.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from jobagent.config import Config

DEFAULT_MAX_TOKENS = 4096


class LLMError(Exception):
    """Any failure talking to a provider, or resolving which one to talk to."""


class QuotaExhaustedError(LLMError):
    """A quota that will not clear inside this run — a daily free-tier cap.

    Distinct from a rate limit, which backing off does fix. Retrying a daily
    cap spends the remaining allowance faster and delays the failure by a
    minute per attempt.
    """


class RetryableLLMError(LLMError):
    """A transient provider failure: overloaded, rate limited, or a network
    blip. Worth trying again; a bad key or a malformed request is not."""


# Statuses worth a second attempt. 529 is Anthropic's "overloaded"; 503 is what
# Gemini returns under load, which it does often enough to stall a batch.
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})

RETRY_ATTEMPTS = 4
RETRY_BASE_DELAY = 2.0


class Provider(str, Enum):
    anthropic = "anthropic"
    gemini = "gemini"


class CallType(str, Enum):
    """The kinds of model call the app makes. Each maps to a provider+model."""

    triage = "triage"
    parse_jd = "parse_jd"
    score = "score"
    generate = "generate"
    prep = "prep"


@dataclass
class CallRoute:
    provider: Provider
    model: str


@dataclass
class LLMResponse:
    text: str
    provider: Provider
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    label: str | None = None
    # True when the provider stopped because the token budget ran out, rather
    # than because the model had finished. The answer is a fragment.
    truncated: bool = False


# --------------------------------------------------------------------------- #
# Cost estimation (best-effort — for the eval harness, not billing)
# --------------------------------------------------------------------------- #

# (input, output) USD per 1M tokens. Keyed by a substring of the model id so
# dated snapshots resolve too. Prices drift; treat every figure as an estimate.
_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4": (5.0, 25.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4": (1.0, 5.0),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-1.5-flash": (0.075, 0.30),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated USD cost of a call, or None if the model isn't in the table."""
    for prefix, (in_price, out_price) in _PRICES_PER_MTOK.items():
        if prefix in model:
            return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return None


# --------------------------------------------------------------------------- #
# Client interface
# --------------------------------------------------------------------------- #


class LLMClient(ABC):
    """One configured provider+model. Construct via ``get_client``."""

    provider: ClassVar[Provider]

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        runs_log_path: Path | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._runs_log_path = runs_log_path
        self._sdk_client = None  # created lazily on first call

    @abstractmethod
    def _complete(
        self, *, system: str | None, prompt: str, max_tokens: int
    ) -> LLMResponse:
        """Provider-specific single call. Returns text + token counts; the base
        class fills in cost and logging."""

    def complete(
        self,
        *,
        prompt: str,
        system: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        label: str | None = None,
    ) -> LLMResponse:
        """One completion. ``label`` is the prompt name, recorded in the run log.

        Transient provider failures are retried with exponential backoff. A
        single overloaded response should not lose a batch of job ads midway.
        """
        response = self._complete_with_retry(
            system=system, prompt=prompt, max_tokens=max_tokens
        )
        response.label = label
        response.cost_usd = estimate_cost(
            response.model, response.input_tokens, response.output_tokens
        )
        self._log_run(response)
        return response

    def _complete_with_retry(
        self, *, system: str | None, prompt: str, max_tokens: int
    ) -> LLMResponse:
        delay = RETRY_BASE_DELAY
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                return self._complete(
                    system=system, prompt=prompt, max_tokens=max_tokens
                )
            except RetryableLLMError:
                if attempt == RETRY_ATTEMPTS:
                    raise
                time.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")  # pragma: no cover

    def complete_json(
        self,
        *,
        prompt: str,
        system: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        label: str | None = None,
        retries: int = 1,
    ) -> tuple[dict, LLMResponse]:
        """Completion constrained to JSON. Parses defensively and retries once
        (by default) with the parse error fed back. Returns (parsed, response)
        for the successful attempt. Raises ``LLMError`` if all attempts fail."""
        base = (
            f"{prompt}\n\n"
            "Respond with a single valid JSON value and nothing else — "
            "no prose, no explanation, no markdown code fences."
        )
        attempt_prompt = base
        last_error: Exception | None = None

        for _ in range(retries + 1):
            response = self.complete(
                prompt=attempt_prompt,
                system=system,
                max_tokens=max_tokens,
                label=label,
            )
            # A truncated answer is a fragment, not a mistake. Retrying it
            # against the same ceiling produces the same fragment and bills
            # for it again — a long job ad cost three of these before the flag
            # existed. Fail immediately and name the cause.
            if response.truncated:
                raise LLMError(
                    f"{self.provider.value}:{self.model} ran out of output "
                    f"tokens at max_tokens={max_tokens:,} and returned an "
                    "incomplete answer. Raise the caller's token budget — "
                    "retrying will hit the same ceiling."
                )
            try:
                return _parse_json(response.text), response
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                attempt_prompt = (
                    f"{base}\n\n"
                    f"Your previous response could not be parsed as JSON "
                    f"({exc}). Return only valid JSON."
                )

        raise LLMError(
            f"{self.provider.value}:{self.model} did not return valid JSON "
            f"after {retries + 1} attempt(s): {last_error}"
        )

    def _log_run(self, response: LLMResponse) -> None:
        """Append one line to the run log. Never let logging break a call."""
        if self._runs_log_path is None:
            return
        record = {
            "ts": time.time(),
            "label": response.label,
            "provider": response.provider.value,
            "model": response.model,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cost_usd": response.cost_usd,
            # The one field that explains a failed call after the fact.
            "truncated": response.truncated,
        }
        try:
            with open(self._runs_log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except OSError:
            pass


def _parse_json(text: str) -> dict:
    """Parse JSON, tolerating a ```json fenced block wrapping it."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Drop the opening fence line (``` or ```json) and the closing fence.
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return json.loads(cleaned)


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #


class AnthropicClient(LLMClient):
    provider = Provider.anthropic

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        runs_log_path: Path | None = None,
        workspace_id: str | None = None,
    ) -> None:
        super().__init__(model, api_key=api_key, runs_log_path=runs_log_path)
        # Identity-linked keys (the kind issued to a user rather than to a
        # workspace) are rejected without an anthropic-workspace-id header.
        # Workspace-scoped keys ignore it, so sending it when set is safe.
        self._workspace_id = workspace_id

    def _sdk(self):
        if self._sdk_client is None:
            import anthropic

            kwargs: dict = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._workspace_id:
                kwargs["default_headers"] = {
                    "anthropic-workspace-id": self._workspace_id
                }
            self._sdk_client = anthropic.Anthropic(**kwargs)
        return self._sdk_client

    def _complete(
        self, *, system: str | None, prompt: str, max_tokens: int
    ) -> LLMResponse:
        import anthropic

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        try:
            message = self._sdk().messages.create(**kwargs)
        except anthropic.APIError as exc:
            if getattr(exc, "status_code", None) in _RETRYABLE_STATUS:
                raise RetryableLLMError(
                    f"Anthropic transient failure ({self.model}): {exc}"
                ) from exc
            if "anthropic-workspace-id" in str(exc) and not self._workspace_id:
                raise LLMError(
                    f"Anthropic rejected the call ({self.model}): this is an "
                    "identity-linked API key, which must name a workspace. Set "
                    "ANTHROPIC_WORKSPACE_ID in .env (Console → Settings → "
                    "Workspaces), or issue a workspace-scoped key instead."
                ) from exc
            raise LLMError(f"Anthropic call failed ({self.model}): {exc}") from exc

        text = "".join(
            block.text for block in message.content if block.type == "text"
        )
        truncated = getattr(message, "stop_reason", None) == "max_tokens"
        return LLMResponse(
            text=text,
            provider=self.provider,
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            truncated=truncated,
        )


# --------------------------------------------------------------------------- #
# Google Gemini
# --------------------------------------------------------------------------- #


class GeminiClient(LLMClient):
    provider = Provider.gemini

    def _sdk(self):
        if self._sdk_client is None:
            from google import genai

            self._sdk_client = genai.Client(api_key=self._api_key)
        return self._sdk_client

    def _complete(
        self, *, system: str | None, prompt: str, max_tokens: int
    ) -> LLMResponse:
        from google.genai import types
        from google.genai import errors as genai_errors

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            system_instruction=system or None,
        )
        try:
            result = self._sdk().models.generate_content(
                model=self.model, contents=prompt, config=config
            )
        except genai_errors.APIError as exc:
            if _is_daily_quota(exc):
                raise QuotaExhaustedError(
                    f"{self.model} has used up its free-tier allowance for "
                    "today. Backing off will not clear it — a daily cap resets "
                    "on Google's clock, not after a wait. Either switch "
                    "BUDGET_MODEL to another model, or drop --budget and pay "
                    "for the run."
                ) from exc
            if getattr(exc, "code", None) in _RETRYABLE_STATUS:
                raise RetryableLLMError(
                    f"Gemini transient failure ({self.model}): {exc}"
                ) from exc
            raise LLMError(f"Gemini call failed ({self.model}): {exc}") from exc

        usage = result.usage_metadata
        return LLMResponse(
            text=result.text or "",
            provider=self.provider,
            model=self.model,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )


def _is_daily_quota(exc: Exception) -> bool:
    """True for a per-day free-tier cap, as opposed to a per-minute limit.

    Matched on the quota id Google returns rather than on the status code:
    429 covers both, and only one of them is worth retrying.
    """
    if getattr(exc, "code", None) != 429:
        return False
    text = str(exc)
    return "PerDay" in text or "per day" in text.lower()


_CLIENTS: dict[Provider, type[LLMClient]] = {
    Provider.anthropic: AnthropicClient,
    Provider.gemini: GeminiClient,
}


# --------------------------------------------------------------------------- #
# Routing + factory
# --------------------------------------------------------------------------- #


def _parse_route(raw: str) -> CallRoute:
    if ":" not in raw:
        raise LLMError(
            f"Invalid route {raw!r}: expected 'provider:model' "
            "(e.g. 'anthropic:claude-sonnet-4-6')"
        )
    provider_part, model = (part.strip() for part in raw.split(":", 1))
    try:
        provider = Provider(provider_part)
    except ValueError:
        known = ", ".join(p.value for p in Provider)
        raise LLMError(
            f"Unknown provider {provider_part!r} in route {raw!r}. Known: {known}"
        ) from None
    if not model:
        raise LLMError(f"Route {raw!r} has no model")
    return CallRoute(provider=provider, model=model)


def resolve_route(config: "Config", call_type: CallType) -> CallRoute:
    """Pick the provider+model for a call type, in priority order:

    0. ``BUDGET_MODE``, which overrides everything — see below
    1. the ``LLM_<CALLTYPE>`` config field, if set
    2. ``LLM_DEFAULT``, if set
    3. the legacy anthropic model fallback (triage → ``ANTHROPIC_TRIAGE_MODEL``,
       everything else → ``ANTHROPIC_MODEL``)

    Budget mode sits above the per-call routing rather than beside it on
    purpose: a half-applied budget mode — cheap parsing, expensive scoring —
    is the shape of an unwelcome bill, and the point of the switch is that one
    setting covers every call the tool makes.
    """
    if config.budget_mode:
        return _parse_route(config.budget_model)

    per_call = {
        CallType.triage: config.llm_triage,
        CallType.parse_jd: config.llm_parse,
        CallType.score: config.llm_score,
        CallType.generate: config.llm_generate,
        CallType.prep: config.llm_prep,
    }[call_type]

    raw = per_call or config.llm_default
    if raw:
        return _parse_route(raw)

    fallback = (
        config.anthropic_triage_model
        if call_type is CallType.triage
        else config.anthropic_model
    )
    if fallback:
        return CallRoute(provider=Provider.anthropic, model=fallback)

    raise LLMError(
        f"No model configured for call type {call_type.value!r}. Set "
        f"LLM_{call_type.value.upper()}, LLM_DEFAULT, or the ANTHROPIC_* fallback."
    )


def get_client(call_type: CallType, config: "Config | None" = None) -> LLMClient:
    """Build the configured client for a call type."""
    if config is None:
        from jobagent.config import get_config

        config = get_config()

    route = resolve_route(config, call_type)
    if route.provider is Provider.anthropic:
        return AnthropicClient(
            model=route.model,
            api_key=config.anthropic_api_key,
            runs_log_path=config.runs_log_path,
            workspace_id=config.anthropic_workspace_id,
        )
    return _CLIENTS[route.provider](
        model=route.model,
        api_key=config.gemini_api_key,
        runs_log_path=config.runs_log_path,
    )
