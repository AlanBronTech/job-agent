"""services.reapply and the refusal in score/generate. Invented data.

SC-001: the worked example spends nothing, both ways (number in the ad, and not).
SC-005: a different job at the same company is never refused.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobagent.adapters.llm import RunContext
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import ApplicationStatus, FitAssessment, OutsideApplication, Verdict
from jobagent.services import documents, reapply, scoring
from jobagent.services.refusals import PossiblySameJob, ProfileMissing, SameJobRecently
from jobagent.services.workspace import Workspace
from tests.ui_seed import assessment, jd, workspace

EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
CONFIG = Config(_env_file=None, llm_default="anthropic:claude-sonnet-5")
TODAY = date(2026, 10, 4)
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


@pytest.fixture
def ws(tmp_path):
    base = workspace(tmp_path)
    return Workspace(**{**base.__dict__, "profile_dir": EXAMPLE_PROFILE})


@pytest.fixture
def model(monkeypatch):
    """Booby-trapped until a test lets the model through."""
    state = SimpleNamespace(scored=[], allow=False)

    def client(*a, **k):
        if not state.allow:
            raise AssertionError("a client was built before the reapply check")
        return object()

    def score_fit(jd_, profile, *, client):
        state.scored.append(jd_.id)
        return FitAssessment(jd_id=jd_.id, overall_score=70, recruiter_screen_score=60,
                             verdict=Verdict.apply, rationale="Invented.", target_role_match=True,
                             target_role_note="Invented.", scored_at=NOW)

    monkeypatch.setattr(scoring, "get_client", client)
    monkeypatch.setattr(documents, "get_client", client)
    monkeypatch.setattr(scoring, "score_fit", score_fit)
    return state


def add_ad(ws, *, req=None, title="Engineering Manager", company="Fabrikam Medical", scored=False):
    with store.open_store(ws.db_path) as conn:
        a = jd(title, company, 30)
        a.requisition_id = req
        jd_id = store.add_jd(conn, a)
        if scored:
            store.add_assessment(conn, assessment(jd_id, Verdict.apply, 70, 60))
    return jd_id


def add_outside(ws, days_ago, *, req=None, title="Engineering Manager"):
    with store.open_store(ws.db_path) as conn:
        store.add_outside(conn, OutsideApplication(
            company="Fabrikam Medical", title=title, requisition_id=req,
            applied_on=TODAY - timedelta(days=days_ago),
            status=ApplicationStatus.applied_no_reply, created_at=NOW))


def score(ws, jd_id):
    return scoring.score(ws, CONFIG, RunContext(command="score", source="ui"), jd_id, today=TODAY)


# -- SC-001, both ways ----------------------------------------------------------


def test_number_in_the_ad_is_refused_before_a_client(ws, model):
    add_outside(ws, 150, req="JR_000123")
    jd_id = add_ad(ws, req="JR-000123")
    with pytest.raises(SameJobRecently) as refused:
        score(ws, jd_id)
    assert refused.value.match.age_days == 150 and model.scored == []


def test_no_number_in_the_ad_asks_then_follows_the_answer(ws, model):
    add_outside(ws, 150, req="JR_000123")
    jd_id = add_ad(ws)
    with pytest.raises(PossiblySameJob):
        score(ws, jd_id)

    reapply.decide(ws, jd_id, "same", "outside:1")
    with pytest.raises(SameJobRecently):
        score(ws, jd_id)

    reapply.decide(ws, jd_id, "different", "outside:1")
    model.allow = True
    score(ws, jd_id)
    assert model.scored == [jd_id]


def test_generate_is_refused_the_same_way(ws, model):
    add_outside(ws, 30, req="JR_000123")
    jd_id = add_ad(ws, req="JR_000123", scored=True)
    with pytest.raises(SameJobRecently):
        documents.generate(ws, CONFIG, RunContext(command="generate"), jd_id, resume=True,
                           cover=False, questions=[], today=TODAY, now=NOW)


def test_the_plan_carries_the_state(ws, model):
    add_outside(ws, 30, req="JR_000123")
    jd_id = add_ad(ws, req="JR_000123", scored=True)
    plan = documents.plan(ws, jd_id, resume=True, cover=False, answers=False, when=TODAY)
    assert plan.reapply.kind == "same"


# -- overrule ---------------------------------------------------------------------


def test_overrule_is_per_ad(ws, model):
    add_outside(ws, 30, req="JR_000123")
    first = add_ad(ws, req="JR_000123")
    second = add_ad(ws, req="JR_000123")
    reapply.decide(ws, first, "overrule", "outside:1")
    model.allow = True
    score(ws, first)
    with pytest.raises(SameJobRecently):
        score(ws, second)


# -- SC-005 and the edges ---------------------------------------------------------


def test_a_different_job_at_the_same_company_scores_normally(ws, model):
    add_outside(ws, 30, req="JR_000123")
    jd_id = add_ad(ws, req="JR_000456")
    model.allow = True
    score(ws, jd_id)
    assert model.scored == [jd_id]


def test_a_different_title_without_numbers_scores_normally(ws, model):
    add_outside(ws, 30)
    jd_id = add_ad(ws, title="Senior Engineering Manager")
    model.allow = True
    score(ws, jd_id)
    assert model.scored == [jd_id]


def test_two_ads_with_one_number_once_one_is_scored(ws, model):
    first = add_ad(ws, req="JR_000789", scored=True)
    second = add_ad(ws, req="JR_000789")
    with pytest.raises(SameJobRecently) as refused:
        score(ws, second)
    assert refused.value.match.against == f"ad:{first}"


def test_no_profile_means_the_profile_refusal_fires(ws, model):
    add_outside(ws, 30, req="JR_000123")
    jd_id = add_ad(ws, req="JR_000123")
    bare = Workspace(**{**ws.__dict__, "profile_dir": None})
    with pytest.raises(ProfileMissing):
        score(bare, jd_id)


def test_window_null_turns_the_rule_off(ws, model, tmp_path):
    import shutil

    profile = tmp_path / "profile"
    shutil.copytree(EXAMPLE_PROFILE, profile)
    assets = profile / "assets.yaml"
    assets.write_text(assets.read_text().replace("reapply_window_days: 183", "reapply_window_days: null"))
    off = Workspace(**{**ws.__dict__, "profile_dir": profile})
    add_outside(ws, 30, req="JR_000123")
    jd_id = add_ad(ws, req="JR_000123")
    assert reapply.check(off, jd_id, TODAY).kind == "clear"


def test_decide_refuses_nonsense(ws):
    jd_id = add_ad(ws)
    with pytest.raises(ValueError):
        reapply.decide(ws, jd_id, "maybe")
