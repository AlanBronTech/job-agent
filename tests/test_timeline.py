"""REVIEW-2026-10-16 D3: chronology computed in code, and order claims checked.

The fixture is profile.example, which has the same shape as the case that went
wrong: a contract IC role (Example Bank, 2021–22) that comes *after* the first
management role (Example EdTech, 2018–21). The assessment for JD 85 said the
equivalent contract roles "precede and run alongside his management roles".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobagent.core import timeline
from jobagent.core.profile import load_profile

EXAMPLE = Path(__file__).resolve().parents[1] / "profile.example"


@pytest.fixture
def profile():
    return load_profile(EXAMPLE)


def test_roles_come_in_date_order_with_a_management_tag(profile):
    spans = timeline.roles_in_order(profile)
    assert [s.id for s in spans] == ["pos_build", "payments_lead", "bank_contracts",
                                     "startup_em", "consultancy_lead", "recent_manager"]
    tags = {s.id: s.management for s in spans}
    assert tags["pos_build"] is False and tags["bank_contracts"] is False
    assert tags["payments_lead"] is True and tags["recent_manager"] is True


def test_the_scorer_is_given_the_timeline(profile):
    block = timeline.render(profile)
    assert block.index("Example Hospitality Group") < block.index("Example EdTech") < block.index("Example Bank")
    assert "[management]" in block and "[individual contributor]" in block
    assert "First management role starts 2018" in block


def test_a_false_precedes_claim_is_caught(profile):
    claim = ("Senior IC contract roles (Example Bank & Example Platform Co) precede and run "
             "alongside his management roles.")
    issues = timeline.order_claims(claim, profile)
    assert len(issues) == 1 and "Example Bank" in issues[0]


def test_true_order_claims_pass(profile):
    assert timeline.order_claims("Example Hospitality Group came before his management roles.", profile) == []
    assert timeline.order_claims("Example Bank followed Example EdTech.", profile) == []
    assert timeline.order_claims("Example EdTech preceded Example Startup.", profile) == []


def test_a_false_after_claim_is_caught(profile):
    assert timeline.order_claims("Example EdTech came after Example Startup.", profile)


def test_the_scoring_prompt_carries_the_timeline(profile):
    from jobagent.core.scoring import score_fit
    from tests.quality_seed import RoutedClient, northwind

    client = RoutedClient({"score_fit": {"verdict": "skip", "overall_score": 10,
                                         "recruiter_screen_score": 10, "rationale": "x",
                                         "target_role_match": False, "target_role_note": "x"}})
    score_fit(northwind(), profile, client=client)
    prompt = client.prompts["score_fit"][0]
    assert "<timeline>" in prompt and "First management role starts 2018" in prompt


def test_a_wrong_order_in_the_assessment_is_reported(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from jobagent.adapters.llm import RunContext
    from jobagent.config import Config
    from jobagent.core.models import FitAssessment, MatchStatus, RequirementMatch, Verdict
    from jobagent.services import scoring
    from jobagent.services.workspace import Workspace
    from tests.ui_seed import seed, workspace

    ws = Workspace(**{**workspace(tmp_path).__dict__, "profile_dir": EXAMPLE})
    ids = seed(ws)
    monkeypatch.setattr(scoring.role_kind, "ensure", lambda *a, **k: None)
    monkeypatch.setattr(scoring, "score_fit", lambda jd, profile, *, client: FitAssessment(
        jd_id=jd.id, overall_score=56, recruiter_screen_score=40, verdict=Verdict.apply_with_caveats,
        rationale="On target.", target_role_match=True, target_role_note="EM.",
        requirements=[RequirementMatch(
            requirement="A background as a Senior IC before moving into management.",
            status=MatchStatus.met, evidence_ref="bank_contracts",
            note="Senior IC contract roles (Example Bank) precede and run alongside his management roles.")],
        scored_at=datetime.now(timezone.utc)))
    result = scoring.score(ws, Config(_env_file=None), RunContext(command="score"), ids["contoso"],
                           client_factory=lambda: object())
    assert any("dates say otherwise" in w and "Example Bank" in w for w in result.warnings)


# -- REVIEW-2026-10-16 D4: management tenure is cumulative ---------------------------


def test_management_tenure_adds_up_across_roles(profile):
    """Example EdTech 2018–2021, Example Startup 2023–24, Example Consultancy 2024–25,
    Example Manufacturing 2025–26: no single role is 2+ years except the first,
    and the total is what a "2+ years as an EM" requirement asks about."""
    months = timeline.management_months(profile, today=__import__("datetime").date(2026, 10, 16))
    assert months == 36 + 12 + 12 + 12
    assert "Management tenure, dated roles added up: 72 months (6 years)" in timeline.render(profile)


def test_a_title_on_the_equivalent_list_or_the_flag_counts_as_management(profile):
    sdm = profile.roles.roles[0]
    assert sdm.title == "Software Development Manager" and timeline.is_management(sdm)
    ic = next(r for r in profile.roles.roles if r.id == "pos_build")
    assert not timeline.is_management(ic)
    flagged = ic.model_copy(update={"people_management": True})
    assert timeline.is_management(flagged)
    narrow = timeline.is_management(sdm, titles=("engineering manager",))
    assert narrow is False  # the list is configurable


def test_the_scorer_is_told_tenure_requirements_are_cumulative():
    prompt = open(EXAMPLE.parent / "prompts" / "score_fit.md").read()
    assert "cumulative" in prompt and "Management tenure" in prompt


# -- 2026-10-26: the dated total was read as the whole career ----------------------


def _with(profile, *, founder=None, earlier=None):
    roles = profile.roles
    if founder is not None:
        roles = roles.model_copy(update={"founder_track_record": [
            e.model_copy(update=founder) for e in roles.founder_track_record]})
    if earlier is not None:
        roles = roles.model_copy(update={"earlier_career": [
            e.model_copy(update=earlier) for e in roles.earlier_career]})
    return profile.model_copy(update={"roles": roles})


def test_a_venture_counts_only_when_flagged_as_managing_people(profile):
    today = __import__("datetime").date(2026, 10, 16)
    dated = {"start": "2010-01", "end": "2012-01"}
    unflagged = _with(profile, founder=dated)
    assert timeline.management_months(unflagged, today=today) == 72
    flagged = _with(profile, founder={**dated, "people_management": True})
    assert timeline.management_months(flagged, today=today) == 72 + 24
    assert "First management role starts 2010-01" in timeline.render(flagged)


def test_undated_leadership_is_named_and_the_total_called_a_minimum(profile):
    assert "undated" not in timeline.render(profile)
    led = _with(profile, earlier={"people_management": True})
    block = timeline.render(led)
    assert "Leadership before these, undated and so not in the total" in block
    assert "The total is a minimum" in block
    assert timeline.management_months(led) == timeline.management_months(profile)


def test_a_tenure_question_is_never_answered_with_a_number():
    prompt = open(EXAMPLE.parent / "prompts" / "score_fit.md").read()
    assert "never\n   with a number of months or years" in prompt
    assert "That total is a minimum" in prompt


# -- REVIEW-2026-10-16 D8: push-on answers grounded in dates, and framed for the ad --


def test_a_years_at_claim_the_dates_do_not_support_is_caught(profile):
    text = "The work he's proudest of took years at Example EdTech and Example Manufacturing Co."
    problems = timeline.duration_claims(text, profile)
    assert len(problems) == 1 and "Example Manufacturing Co" in problems[0] and "12 months" in problems[0]
    assert timeline.duration_claims("He spent years at Example EdTech.", profile) == []


def test_the_scorer_is_told_not_to_lead_with_contracting_for_a_permanent_role():
    prompt = open(EXAMPLE.parent / "prompts" / "score_fit.md").read()
    assert "permanent" in prompt and "contracting pattern" in prompt


def test_a_venture_that_hired_later_counts_from_when_the_managing_began(profile):
    today = __import__("datetime").date(2026, 10, 16)
    late = _with(profile, founder={"start": "2008-01", "end": "2012-01",
                                   "people_management": True, "management_from": "2011-01"})
    assert timeline.management_months(late, today=today) == 72 + 12
    block = timeline.render(late)
    assert "2008-01 to 2012-01" in block and "managing people from 2011-01" in block
    assert "First management role starts 2011-01" in block
