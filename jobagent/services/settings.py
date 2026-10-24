"""Which model each step uses, how hard it thinks, and which checks run.

Chosen on the UI's Settings page and saved as `settings.json` beside the
database, so the demo workspace and the real one keep their own. A setting
here overrides `.env`; a step left on "default" falls through to `.env` and
then to the built-in defaults (free tier for reading and classifying ads,
Haiku for the screen; see adapters/llm.py).

`apply` is called by `get_config()` and by the UI on every request, so the
CLI and the browser always agree and a change needs no restart.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from jobagent.adapters.llm import (
    DEFAULT_EFFORT,
    EFFORT_LEVELS,
    CallType,
    LLMError,
    Provider,
    parse_efforts,
    resolve_route,
)
from jobagent.adapters.prices import PriceError, load_prices

FILE_NAME = "settings.json"


@dataclass(frozen=True)
class Step:
    key: str            # settings key and LLM_EFFORT key
    call_type: CallType
    field: str          # Config field holding its route
    label: str
    sees: str           # what the model is shown: why free may or may not suit


STEPS: tuple[Step, ...] = (
    Step("parse_jd", CallType.parse_jd, "llm_parse", "Read an ad", "the ad only"),
    Step("classify", CallType.classify, "llm_classify", "Classify the role", "the ad only"),
    Step("triage", CallType.triage, "llm_triage", "First-pass screen", "the ad and a profile summary"),
    Step("score", CallType.score, "llm_score", "Score fit", "the ad and your full profile"),
    Step("generate", CallType.generate, "llm_generate", "Write documents", "the ad and your full profile"),
    Step("prep", CallType.prep, "llm_prep", "Interview prep", "the ad and your full profile"),
    Step("review", CallType.review, "llm_review", "Claim check and review", "the documents and their evidence"),
    Step("repair", CallType.repair, "llm_repair", "Repair a flagged sentence", "the sentence and its evidence"),
)


def path_for(config) -> Path:
    return Path(config.db_path).expanduser().parent / FILE_NAME


def load(config) -> dict:
    try:
        data = json.loads(path_for(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(config, data: dict) -> Path:
    target = path_for(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def apply(config):
    """The config with the saved settings laid over it. Never raises."""
    data = load(config)
    if not data:
        return config
    update: dict = {}
    for step in STEPS:
        route = (data.get("routes") or {}).get(step.key)
        if route:
            update[step.field] = route
    efforts = {k: v for k, v in (data.get("efforts") or {}).items()
               if v in (*EFFORT_LEVELS, "default")}
    if efforts:
        merged = {**parse_efforts(config.llm_effort), **efforts}
        update["llm_effort"] = ",".join(f"{k}={v}" for k, v in sorted(merged.items()))
    for flag in ("check_claims", "review"):
        if isinstance(data.get(flag), bool):
            update[flag] = data[flag]
    return config.model_copy(update=update) if update else config


# --------------------------------------------------------------------------- #
# What the page offers
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModelOption:
    route: str      # "provider:model"
    label: str
    price: str      # "$1.00 / $5.00 per million tokens", or "free tier"
    available: bool  # a key for its provider is set


_NAMES = {
    "gemini-2.5-flash": ("Gemini 2.5 Flash", True),
    "gemini-2.5-flash-lite": ("Gemini 2.5 Flash-Lite", True),
    "gemini-2.5-pro": ("Gemini 2.5 Pro", False),
    "claude-haiku-4-5": ("Claude Haiku 4.5", False),
    "claude-sonnet-5": ("Claude Sonnet 5", False),
    "claude-opus-5": ("Claude Opus 5", False),
}
# The API names a price-table key may need, where it differs.
_API_ID = {"claude-haiku-4-5": "claude-haiku-4-5-20251001"}


def model_options(config) -> list[ModelOption]:
    try:
        prices = load_prices()
        lookup = prices.lookup
    except PriceError:
        lookup = lambda _m: None  # noqa: E731
    options = []
    for key, (name, free) in _NAMES.items():
        provider = Provider.gemini if key.startswith("gemini") else Provider.anthropic
        route = f"{provider.value}:{_API_ID.get(key, key)}"
        price = lookup(key)
        cost = f"${price[0]:.2f} in / ${price[1]:.2f} out per million tokens" if price else "price unknown"
        if free:
            cost = f"free tier (daily cap, then the fallback model); else {cost}"
        options.append(ModelOption(route, name, cost, _has_key(config, provider)))
    return options


def _has_key(config, provider: Provider) -> bool:
    if provider is Provider.gemini:
        return bool(config.gemini_api_key or os.environ.get("GEMINI_API_KEY"))
    return bool(config.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))


@dataclass
class StepView:
    step: Step
    chosen: str           # the saved route, or "" for default
    default_route: str    # what "default" resolves to now
    effort: str           # saved effort or "default"
    default_effort: str


def view(config) -> dict:
    """Everything the Settings page shows, resolved against the current config."""
    data = load(config)
    steps = []
    for step in STEPS:
        try:
            resolved = resolve_route(config, step.call_type)
            default_route = f"{resolved.provider.value}:{resolved.model}"
        except LLMError:
            default_route = "none configured"
        steps.append(StepView(
            step=step,
            chosen=(data.get("routes") or {}).get(step.key, ""),
            default_route=default_route,
            effort=(data.get("efforts") or {}).get(step.key, "default"),
            default_effort=DEFAULT_EFFORT.get(step.call_type.value, "model decides"),
        ))
    effective = apply(config)
    return {
        "steps": steps,
        "models": model_options(config),
        "check_claims": effective.check_claims,
        "review": effective.review,
        "efforts": EFFORT_LEVELS,
        "path": path_for(config),
    }


def from_form(form) -> dict:
    """The saved shape, from the Settings form. Unknown values are dropped."""
    routes, efforts = {}, {}
    valid_routes = {o.route for o in model_options_for_validation()}
    for step in STEPS:
        route = str(form.get(f"route_{step.key}") or "")
        if route in valid_routes:
            routes[step.key] = route
        effort = str(form.get(f"effort_{step.key}") or "default")
        if effort in EFFORT_LEVELS:
            efforts[step.key] = effort
    return {
        "routes": routes,
        "efforts": efforts,
        "check_claims": form.get("check_claims") == "1",
        "review": form.get("review") == "1",
    }


def model_options_for_validation() -> list[ModelOption]:
    return [ModelOption(f"{('gemini' if k.startswith('gemini') else 'anthropic')}:{_API_ID.get(k, k)}",
                        n, "", True) for k, (n, _f) in _NAMES.items()]

