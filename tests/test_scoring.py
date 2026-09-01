"""Unit tests for fit scoring.

The hard filters get the bulk of the attention. They are the part that must
behave identically every time — they encode decisions Alan has already made,
and a tool that re-argues them is worse than no tool. The model's half is
exercised through a fake client.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jobagent.adapters.llm import LLMClient, LLMError, LLMResponse, Provider
from jobagent.core.models import (
    AssetsFile,
    ConstraintStatus,
    HiringStatus,
    JobDescription,
    SalaryRange,
    TargetFilters,
    Verdict,
    WorkArrangement,
    WorkType,
)
from jobagent.core.scoring import ScoringError, check_constraints, score_fit

FILTERS = TargetFilters(
    location="Sydney CBD, Sydney North Shore, train-accessible",
    max_commute_minutes=60,
    max_commute_basis="hybrid",
    max_commute_rationale="Hard constraint, one way.",
    onsite_locations=["Sydney CBD", "Sydney North Shore"],
    onsite_rationale="Five days a week is geographic and absolute.",
    min_salary_aud=150000,
    work_types=["permanent", "contract", "fractional"],
)


def make_jd(**overrides) -> JobDescription:
    data = {
        "id": 1,
        "title": "Engineering Manager",
        "company": "Acme",
        "location": "Sydney CBD",
        "work_type": WorkType.permanent,
        "work_arrangement": WorkArrangement.remote,
        "salary_range": SalaryRange(min_aud=180000, max_aud=200000, raw="$180k–$200k"),
        "raw_text": "Engineering Manager at Acme.",
        "ingested_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return JobDescription(**data)


def make_profile(profile_factory, filters: TargetFilters = FILTERS):
    """The example profile with target_filters replaced by the ones here.

    profile.example carries a placeholder salary floor of zero, which would
    make every salary check pass and test nothing.
    """
    from jobagent.core.profile import load_profile

    profile = load_profile(profile_factory())
    profile.assets = AssetsFile(
        narrative=profile.assets.narrative,
        differentiators=profile.assets.differentiators,
        target_roles=profile.assets.target_roles,
        target_filters=filters,
        positive_signals=profile.assets.positive_signals,
        negative_signals=profile.assets.negative_signals,
    )
    return profile


def constraint(checks, name):
    return next(check for check in checks if check.name == name)


# --------------------------------------------------------------------------- #
# Hard filters — hiring status and work type
# --------------------------------------------------------------------------- #


def test_a_closed_ad_is_a_breach(profile_factory) -> None:
    checks = check_constraints(
        make_jd(hiring_status=HiringStatus.closed), make_profile(profile_factory)
    )

    assert constraint(checks, "hiring status").status is ConstraintStatus.breach


def test_an_accepted_work_type_passes(profile_factory) -> None:
    checks = check_constraints(
        make_jd(work_type=WorkType.contract), make_profile(profile_factory)
    )

    assert constraint(checks, "work type").status is ConstraintStatus.ok


def test_an_unaccepted_work_type_is_a_breach(profile_factory) -> None:
    checks = check_constraints(
        make_jd(work_type=WorkType.fixed_term), make_profile(profile_factory)
    )

    assert constraint(checks, "work type").status is ConstraintStatus.breach


def test_an_unstated_work_type_is_a_question(profile_factory) -> None:
    checks = check_constraints(
        make_jd(work_type=WorkType.unknown), make_profile(profile_factory)
    )
    check = constraint(checks, "work type")

    assert check.status is ConstraintStatus.unknown
    assert check.question


# --------------------------------------------------------------------------- #
# Hard filters — location
# --------------------------------------------------------------------------- #


def test_remote_has_no_commute_constraint(profile_factory) -> None:
    checks = check_constraints(
        make_jd(work_arrangement=WorkArrangement.remote),
        make_profile(profile_factory),
    )

    assert constraint(checks, "location").status is ConstraintStatus.ok


def test_onsite_in_an_accepted_place_passes(profile_factory) -> None:
    checks = check_constraints(
        make_jd(work_arrangement=WorkArrangement.onsite, location="Sydney CBD"),
        make_profile(profile_factory),
    )

    assert constraint(checks, "location").status is ConstraintStatus.ok


def test_onsite_somewhere_else_in_sydney_is_not_assumed_to_pass(
    profile_factory,
) -> None:
    """The Smeaton Grange lesson. "Sydney NSW" does not name "Sydney CBD", and
    treating it as if it did is the exact failure the filter exists to stop."""
    checks = check_constraints(
        make_jd(work_arrangement=WorkArrangement.onsite, location="Sydney NSW"),
        make_profile(profile_factory),
    )
    check = constraint(checks, "location")

    assert check.status is ConstraintStatus.unknown
    assert check.question


def test_onsite_with_no_suburb_is_a_question_not_a_pass(profile_factory) -> None:
    """The CareGP case: the ad said on-site and named no suburb."""
    checks = check_constraints(
        make_jd(work_arrangement=WorkArrangement.onsite, location=None),
        make_profile(profile_factory),
    )

    assert constraint(checks, "location").status is ConstraintStatus.unknown


def test_hybrid_always_raises_the_commute_question(profile_factory) -> None:
    checks = check_constraints(
        make_jd(work_arrangement=WorkArrangement.hybrid, location="North Sydney"),
        make_profile(profile_factory),
    )
    check = constraint(checks, "location")

    assert check.status is ConstraintStatus.unknown
    assert "60" in check.question


# --------------------------------------------------------------------------- #
# Hard filters — salary
# --------------------------------------------------------------------------- #


def test_a_band_above_the_floor_passes(profile_factory) -> None:
    checks = check_constraints(make_jd(), make_profile(profile_factory))

    assert constraint(checks, "salary").status is ConstraintStatus.ok


def test_a_band_entirely_below_the_floor_is_a_breach(profile_factory) -> None:
    checks = check_constraints(
        make_jd(salary_range=SalaryRange(min_aud=110000, max_aud=130000)),
        make_profile(profile_factory),
    )

    assert constraint(checks, "salary").status is ConstraintStatus.breach


def test_a_band_straddling_the_floor_is_unresolved(profile_factory) -> None:
    """Quickli advertised $140,000-$180,000 against a $150,000 floor. Neither
    a pass nor a breach — it depends where in the band an offer lands."""
    checks = check_constraints(
        make_jd(salary_range=SalaryRange(min_aud=140000, max_aud=180000)),
        make_profile(profile_factory),
    )

    assert constraint(checks, "salary").status is ConstraintStatus.unknown


def test_no_band_is_a_question_and_keeps_the_ad_s_own_wording(
    profile_factory,
) -> None:
    checks = check_constraints(
        make_jd(salary_range=SalaryRange(raw="Exceptional Daily Rate")),
        make_profile(profile_factory),
    )
    check = constraint(checks, "salary")

    assert check.status is ConstraintStatus.unknown
    assert "Exceptional Daily Rate" in check.detail


# --------------------------------------------------------------------------- #
# The model's half, and reconciliation
# --------------------------------------------------------------------------- #

MODEL_ANSWER = {
    "overall_score": 78,
    "recruiter_screen_score": 55,
    "verdict": "apply",
    "rationale": "On target and well evidenced.",
    "target_role_match": True,
    "target_role_note": "Engineering Manager, first on target_roles.",
    "requirements": [
        {
            "requirement": "5+ years managing engineering teams",
            "status": "met",
            "evidence_ref": "acme_em",
            "note": "Ran two squads for three years.",
        }
    ],
    "emphasise": ["Lead with the founder track"],
    "challenge_points": [{"point": "Why leaving?", "response": "Recorded reason."}],
    "profile_gaps": [],
    "questions_to_ask": [],
}


class FakeClient(LLMClient):
    """Returns canned JSON. Records the prompt so tests can assert on it."""

    provider = Provider.anthropic

    def __init__(self, payload: object = None, *, error: Exception | None = None):
        super().__init__(model="fake-model")
        self._payload = MODEL_ANSWER if payload is None else payload
        self._error = error
        self.prompt: str | None = None

    def _complete(self, *, system, prompt, max_tokens):  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, *, prompt, label=None, **kwargs):
        self.prompt = prompt
        if self._error is not None:
            raise self._error
        return self._payload, LLMResponse(
            text="{}", model=self.model, provider=self.provider, input_tokens=1,
            output_tokens=1
        )


def test_a_clean_ad_scores_and_keeps_the_model_s_verdict(profile_factory) -> None:
    fit = score_fit(make_jd(), make_profile(profile_factory), client=FakeClient())

    assert fit.verdict is Verdict.apply
    assert fit.overall_score == 78
    assert fit.jd_id == 1
    assert fit.model_used == "fake-model"


def test_a_breached_filter_overrides_an_enthusiastic_model(profile_factory) -> None:
    """The model said apply. The salary is below the floor. The filter wins."""
    jd = make_jd(salary_range=SalaryRange(min_aud=100000, max_aud=120000))

    fit = score_fit(jd, make_profile(profile_factory), client=FakeClient())

    assert fit.verdict is Verdict.skip
    assert "Ruled out by a stated filter" in fit.rationale
    # The score is still recorded — it is worth knowing the role fitted.
    assert fit.overall_score == 78


def test_an_unresolved_question_caps_the_verdict(profile_factory) -> None:
    jd = make_jd(work_arrangement=WorkArrangement.hybrid, location="Parramatta")

    fit = score_fit(jd, make_profile(profile_factory), client=FakeClient())

    assert fit.verdict is Verdict.apply_with_caveats
    assert fit.questions_to_ask


def test_questions_from_filters_are_not_duplicated(profile_factory) -> None:
    jd = make_jd(work_arrangement=WorkArrangement.hybrid)
    profile = make_profile(profile_factory)
    client = FakeClient()

    first = score_fit(jd, profile, client=client)
    again = score_fit(jd, profile, client=client)

    assert len(first.questions_to_ask) == len(again.questions_to_ask)


def test_the_prompt_carries_the_profile_the_ad_and_the_filters(
    profile_factory,
) -> None:
    client = FakeClient()

    score_fit(make_jd(), make_profile(profile_factory), client=client)

    assert "target_filters" in client.prompt
    assert "Engineering Manager" in client.prompt
    assert '"name": "salary"' in client.prompt


def test_the_raw_ad_text_is_not_sent_twice(profile_factory) -> None:
    """Every field is already extracted; sending raw_text as well doubles the
    prompt for nothing the scorer can use."""
    client = FakeClient()

    score_fit(
        make_jd(raw_text="MARKER-STRING-NOT-IN-ANY-FIELD"),
        make_profile(profile_factory),
        client=client,
    )

    assert "MARKER-STRING-NOT-IN-ANY-FIELD" not in client.prompt


def test_llm_failure_becomes_a_scoring_error(profile_factory) -> None:
    client = FakeClient(error=LLMError("no key"))

    with pytest.raises(ScoringError, match="Model call failed"):
        score_fit(make_jd(), make_profile(profile_factory), client=client)


def test_a_non_object_answer_is_rejected(profile_factory) -> None:
    with pytest.raises(ScoringError, match="Expected a JSON object"):
        score_fit(make_jd(), make_profile(profile_factory), client=FakeClient(["nope"]))


def test_an_out_of_range_score_reports_schema_drift(profile_factory) -> None:
    payload = dict(MODEL_ANSWER, overall_score=140)

    with pytest.raises(ScoringError, match="did not match the FitAssessment schema"):
        score_fit(make_jd(), make_profile(profile_factory), client=FakeClient(payload))


def test_unexpected_keys_are_dropped_not_fatal(profile_factory) -> None:
    payload = dict(MODEL_ANSWER, confidence="high", salary_guess=170000)

    fit = score_fit(make_jd(), make_profile(profile_factory), client=FakeClient(payload))

    assert fit.overall_score == 78


def test_a_fractional_score_is_rounded_not_rejected(profile_factory) -> None:
    """A model that answers 62.0 means 62. Rejecting it loses the whole
    assessment over a decimal point, which is what happened to two eval cases
    the first time the scorer ran against Gemini."""
    payload = dict(MODEL_ANSWER, overall_score=62.0, recruiter_screen_score=48.5)

    fit = score_fit(make_jd(), make_profile(profile_factory), client=FakeClient(payload))

    assert fit.overall_score == 62
    assert fit.recruiter_screen_score == 48


def test_the_prompt_states_the_score_range(profile_factory) -> None:
    """It did not, in v2, and a weaker model duly scored out of ten."""
    client = FakeClient()

    score_fit(make_jd(), make_profile(profile_factory), client=client)

    assert "0 to 100" in client.prompt


# --------------------------------------------------------------------------- #
# A stub ad is not scoreable
# --------------------------------------------------------------------------- #


def test_a_stub_ad_is_thin() -> None:
    """JD 23 held 565 characters and the scorer still assessed five
    requirements the ad never stated. Right verdict, wrong reasons."""
    assert make_jd(raw_text="Design and implement AI solutions. " * 4).thin is True


def test_a_whole_ad_is_not_thin() -> None:
    assert make_jd(raw_text="w" * 800).thin is False
    assert make_jd(raw_text="w" * 5000).thin is False
