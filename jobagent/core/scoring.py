"""Scoring one job ad against the profile, and deciding whether to apply.

The division of labour here is the whole design, and it comes out of eleven
real applications with recorded outcomes:

* **Hard filters are computed in Python.** Salary floor, employment type,
  on-site geography, closed ads — these are arithmetic and set membership over
  values Alan has already decided. Asking a model to apply them produces
  different answers on different runs, and the failure mode is the tool
  arguing him into a role he ruled out months ago. A breach here overrides the
  model's verdict outright.
* **Judgment is asked of the model.** Which requirements the profile actually
  answers, what to lead with, what a recruiter will push back on. That is
  reading comprehension against 60KB of profile, and it is what a model is for.

The order matters. Of the eleven recorded applications, the one that drew a
considered human response was the only one aimed at a listed target role, and
three of the others were not on ``target_roles`` at all. Deciding *whether the
role is the right shape* did more for the outcomes than scoring *how well he
matches it* ever could, so the shape questions are asked first and can end the
assessment on their own.

Nothing here prints, reads config, or exits.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import yaml
from pydantic import ValidationError

from jobagent.adapters.llm import LLMClient, LLMError
from jobagent.core.models import (
    ConstraintCheck,
    ConstraintStatus,
    FitAssessment,
    HiringStatus,
    JobDescription,
    Profile,
    Verdict,
    WorkArrangement,
    WorkType,
)
from jobagent.core.prompts import PromptError, load_prompt

PROMPT_NAME = "score_fit"

# An assessment is several times the size of a parsed ad: one entry per
# requirement with a note against each, plus challenge points, emphasis and
# questions. The 4,096-token default is tuned for parsing and truncates this
# mid-string. 8,192 was not enough either — the DiUS consulting ad has 23
# must-haves — so the budget is generous and the prompt bounds the verbosity
# instead, which is the part actually worth controlling.
MAX_TOKENS = 16384

# Keys the prompt is contracted to return. Anything else the model volunteers
# is dropped rather than passed to a model with extra="forbid".
_EXPECTED_KEYS = frozenset(
    {
        "overall_score",
        "recruiter_screen_score",
        "verdict",
        "rationale",
        "target_role_match",
        "target_role_note",
        "requirements",
        "emphasise",
        "challenge_points",
        "profile_gaps",
        "questions_to_ask",
    }
)


class ScoringError(Exception):
    """The ad could not be scored against the profile."""


def score_fit(
    jd: JobDescription,
    profile: Profile,
    *,
    client: LLMClient,
    scored_at: datetime | None = None,
) -> FitAssessment:
    """Score one ad. Hard filters first, then the model, then reconciliation."""
    constraints = check_constraints(jd, profile)

    try:
        prompt = load_prompt(
            PROMPT_NAME,
            profile_yaml=_profile_yaml(profile),
            jd_json=_jd_json(jd),
            constraints_json=_constraints_json(constraints),
        )
    except PromptError as exc:
        raise ScoringError(str(exc)) from exc

    try:
        parsed, response = client.complete_json(
            prompt=prompt, label=PROMPT_NAME, max_tokens=MAX_TOKENS
        )
    except LLMError as exc:
        raise ScoringError(f"Model call failed while scoring: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ScoringError(
            f"Expected a JSON object from the model, got {type(parsed).__name__}."
        )

    data = {key: value for key, value in parsed.items() if key in _EXPECTED_KEYS}
    data["jd_id"] = jd.id if jd.id is not None else 0
    data["constraints"] = [check.model_dump() for check in constraints]
    data["model_used"] = response.model
    data["scored_at"] = scored_at or datetime.now(timezone.utc)

    try:
        assessment = FitAssessment.model_validate(data)
    except ValidationError as exc:
        raise ScoringError(
            "The model's answer did not match the FitAssessment schema. "
            f"Either the prompt and the model have drifted apart, or the model "
            f"ignored the contract.\n{exc}"
        ) from exc

    return apply_hard_filters(assessment)


# --------------------------------------------------------------------------- #
# Hard filters
# --------------------------------------------------------------------------- #


def check_constraints(jd: JobDescription, profile: Profile) -> list[ConstraintCheck]:
    """Evaluate every stated filter in ``target_filters`` against one ad."""
    filters = profile.assets.target_filters
    return [
        _check_hiring_status(jd),
        _check_work_type(jd, filters.work_types),
        _check_location(jd, filters),
        _check_salary(jd, filters.min_salary_aud),
    ]


def _check_hiring_status(jd: JobDescription) -> ConstraintCheck:
    if jd.hiring_status is HiringStatus.closed:
        return ConstraintCheck(
            name="hiring status",
            status=ConstraintStatus.breach,
            detail="The ad is no longer accepting applications.",
        )
    return ConstraintCheck(
        name="hiring status",
        status=ConstraintStatus.ok,
        detail="Open, or the ad does not say it is closed.",
    )


def _check_work_type(jd: JobDescription, accepted: list[str]) -> ConstraintCheck:
    if not accepted:
        return ConstraintCheck(
            name="work type",
            status=ConstraintStatus.ok,
            detail="No employment-type preference is recorded.",
        )
    if jd.work_type is WorkType.unknown:
        return ConstraintCheck(
            name="work type",
            status=ConstraintStatus.unknown,
            detail="The ad does not state permanent, contract or fixed term.",
            question="Is this permanent, contract or fixed term?",
        )
    if jd.work_type.value in accepted:
        return ConstraintCheck(
            name="work type",
            status=ConstraintStatus.ok,
            detail=f"{jd.work_type.value} is in {', '.join(accepted)}.",
        )
    return ConstraintCheck(
        name="work type",
        status=ConstraintStatus.breach,
        detail=f"{jd.work_type.value} is not one of {', '.join(accepted)}.",
    )


def _check_location(jd: JobDescription, filters) -> ConstraintCheck:
    """On-site and hybrid are different constraints, per ``target_filters``.

    Five days a week is filtered geographically and absolutely; two days is
    filtered by the commute ceiling. Neither can be decided from an ad that
    names no suburb, which is the CareGP case and is why ``unknown`` exists.
    """
    if jd.work_arrangement is WorkArrangement.remote:
        return ConstraintCheck(
            name="location",
            status=ConstraintStatus.ok,
            detail="Remote — no commute constraint applies.",
        )

    if jd.work_arrangement is WorkArrangement.onsite:
        allowed = filters.onsite_locations
        if not allowed:
            return ConstraintCheck(
                name="location",
                status=ConstraintStatus.breach,
                detail="On-site, and no on-site location is accepted.",
            )
        if jd.location and _names_an_allowed_place(jd.location, allowed):
            return ConstraintCheck(
                name="location",
                status=ConstraintStatus.ok,
                detail=f"On-site in {jd.location}, which is on the accepted list.",
            )
        return ConstraintCheck(
            name="location",
            status=ConstraintStatus.unknown,
            detail=(
                f"On-site in {jd.location or 'an unstated location'}, which does "
                f"not name one of {', '.join(allowed)}. On-site outside those is "
                "an absolute skip, so this cannot be scored until it is known."
            ),
            question=f"Which office is this based in? Accepted: {', '.join(allowed)}.",
        )

    if jd.work_arrangement is WorkArrangement.hybrid:
        return ConstraintCheck(
            name="location",
            status=ConstraintStatus.unknown,
            detail=(
                f"Hybrid in {jd.location or 'an unstated location'}. The "
                f"{filters.max_commute_minutes}-minute one-way ceiling applies "
                "and cannot be checked from the ad."
            ),
            question=(
                f"Is the office within {filters.max_commute_minutes} minutes "
                "one way, and how many days on-site?"
            ),
        )

    return ConstraintCheck(
        name="location",
        status=ConstraintStatus.unknown,
        detail="The ad does not say whether the role is on-site, hybrid or remote.",
        question="Is this on-site, hybrid or remote, and where?",
    )


def _names_an_allowed_place(location: str, allowed: list[str]) -> bool:
    """True if the ad's location names one of the accepted places.

    Deliberately literal. "Sydney NSW" does not name "Sydney CBD" and must not
    be treated as if it did — the whole point of the on-site filter is that
    somewhere else in Sydney is a skip.

    Known limitation, left in on purpose: a location naming two places —
    "Sydney CBD office, relocating to Parramatta in Q1" — passes on the first
    one. Tightening it would have to decide that two places means `unknown`,
    and that judgement would also fire on "Sydney CBD (occasional travel to
    Parramatta)", which is fine. The `detail` line prints the ad's location
    verbatim, so the second place is in front of Alan either way, and a filter
    that turns a passing ad into a question is the failure mode that matters
    more here. Revisit if a real ad is ever mis-passed by it; none has been.
    """
    lowered = location.lower()
    return any(place.lower() in lowered for place in allowed)


def _check_salary(jd: JobDescription, floor: int) -> ConstraintCheck:
    salary = jd.salary_range
    if salary is None or (salary.min_aud is None and salary.max_aud is None):
        return ConstraintCheck(
            name="salary",
            status=ConstraintStatus.unknown,
            detail=(
                f"No band stated; the floor is ${floor:,}."
                + (f' Ad says: "{salary.raw}".' if salary and salary.raw else "")
            ),
            question=f"What is the band? The floor is ${floor:,}.",
        )

    top = salary.max_aud or salary.min_aud
    bottom = salary.min_aud or salary.max_aud
    if top is not None and top < floor:
        return ConstraintCheck(
            name="salary",
            status=ConstraintStatus.breach,
            detail=f"Top of band ${top:,} is below the ${floor:,} floor.",
        )
    if bottom is not None and bottom < floor:
        return ConstraintCheck(
            name="salary",
            status=ConstraintStatus.unknown,
            detail=(
                f"Band ${bottom:,}–${top:,} straddles the ${floor:,} floor. "
                "Whether it clears depends where in the band an offer lands."
            ),
            question=f"Where in the ${bottom:,}–${top:,} band would this land?",
        )
    return ConstraintCheck(
        name="salary",
        status=ConstraintStatus.ok,
        detail=f"Band starts at ${bottom:,}, at or above the ${floor:,} floor.",
    )


def apply_hard_filters(assessment: FitAssessment) -> FitAssessment:
    """Let the constraints override the model, never the other way round.

    A breach ends it: no fit score compensates for a filter Alan has already
    decided. An unresolved unknown caps the verdict — it does not veto the
    role, it says the question has to be answered before the day is spent.
    """
    breaches = assessment.breaches
    if breaches:
        assessment.verdict = Verdict.skip
        reasons = "; ".join(check.detail for check in breaches)
        assessment.rationale = f"Ruled out by a stated filter — {reasons} {assessment.rationale}"
        return assessment

    questions = [check.question for check in assessment.unknowns if check.question]
    for question in questions:
        if question not in assessment.questions_to_ask:
            assessment.questions_to_ask.append(question)

    if questions and assessment.verdict is Verdict.apply:
        assessment.verdict = Verdict.apply_with_caveats

    return assessment


# --------------------------------------------------------------------------- #
# Prompt inputs
# --------------------------------------------------------------------------- #


def _profile_yaml(profile: Profile) -> str:
    """The whole profile, including ``scorer_only`` entries.

    Visibility governs what may be *rendered* into a resume, not what the
    scorer may read. An entry marked ``scorer_only`` exists precisely to
    inform this decision.
    """
    return yaml.safe_dump(
        profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True
    )


def _jd_json(jd: JobDescription) -> str:
    data = jd.model_dump(mode="json")
    # The ad's own text is already summarised by every other field, and
    # including it doubles the prompt for no gain the scorer can use.
    data.pop("raw_text", None)
    return json.dumps(data, indent=2, ensure_ascii=False)


def _constraints_json(constraints: list[ConstraintCheck]) -> str:
    return json.dumps(
        [check.model_dump(mode="json") for check in constraints],
        indent=2,
        ensure_ascii=False,
    )
