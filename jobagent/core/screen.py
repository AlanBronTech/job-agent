"""A cheap first pass before the full assessment (2026-10-14).

Ten of thirteen ads in one batch were skips that could be seen from the title
and the first must-have, and each cost a $0.12 assessment to be told so. The
screen reads the parsed ad against a short summary of the profile on a cheap
model and says `score` or `skip`. It is built to let anything arguable
through: a false skip loses a job, a false `score` only costs what it costs
today. `jobagent eval screen` measures that trade on the labelled cases.

Advisory, never a filter: the decision is stored and shown, and Alan chooses
what to score.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, ValidationError

from jobagent.adapters.llm import LLMClient, LLMError
from jobagent.core.models import JobDescription, Profile, Visibility
from jobagent.core.prompts import PromptError, load_prompt

SCREEN_PROMPT = "screen_fit"
MAX_TOKENS = 4096


class ScreenError(Exception):
    """The screen's answer could not be used."""


class ScreenResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: str  # "score" | "skip"
    reason: str


def screen(jd: JobDescription, profile: Profile, *, client: LLMClient) -> ScreenResult:
    try:
        prompt = load_prompt(
            SCREEN_PROMPT, candidate=candidate_summary(profile), ad_json=_ad(jd)
        )
    except PromptError as exc:
        raise ScreenError(str(exc)) from exc
    try:
        parsed, _ = client.complete_json(prompt=prompt, label=SCREEN_PROMPT, max_tokens=MAX_TOKENS)
        result = ScreenResult.model_validate(parsed)
    except LLMError as exc:
        raise ScreenError(f"Model call failed while screening: {exc}") from exc
    except ValidationError as exc:
        raise ScreenError(f"The screen did not match the contract.\n{exc}") from exc
    if result.decision not in ("score", "skip"):
        # An answer that is neither is not a skip: the full assessment decides.
        result.decision = "score"
    return result


def candidate_summary(profile: Profile) -> str:
    """What a first pass needs, and nothing a scorer note holds."""
    assets = profile.assets
    roles = profile.roles
    lines = ["Targets: " + "; ".join(assets.target_roles)]
    if assets.target_filters.avoid:
        lines.append("Avoids: " + "; ".join(assets.target_filters.avoid))
    lines.append("Work types: " + ", ".join(assets.target_filters.work_types))
    lines.append("Recent roles:")
    for role in roles.roles:
        if role.visibility is Visibility.scorer_only:
            continue
        tech = f" — {', '.join(role.tech[:8])}" if role.tech else ""
        lines.append(f"- {role.title} · {role.company} ({role.sector}){tech}")
    for entry in roles.founder_track_record:
        if entry.visibility is not Visibility.scorer_only:
            lines.append(f"- {entry.role}, {entry.company}")
    skills = [s for values in roles.skills.values() for s in values]
    lines.append("Skills: " + ", ".join(skills[:40]))
    return "\n".join(lines)


def _ad(jd: JobDescription) -> str:
    return json.dumps(
        {
            "title": jd.title,
            "seniority": jd.seniority.value,
            "work_type": jd.work_type.value,
            "work_arrangement": jd.work_arrangement.value,
            "must_haves": jd.must_haves,
            "responsibilities": jd.responsibilities[:8],
            "tech_stack": jd.tech_stack,
        },
        indent=2,
        ensure_ascii=False,
    )
