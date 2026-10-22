"""Contract framing (REVIEW-2026-10-18, task 7): a day rate is judged as a day
rate, a contract ad is matched to a contract offer, and the writer is told.
Every company, figure and offer here is invented."""

from __future__ import annotations

import pytest

from jobagent.core.generate import CONTRACT_NOTE_MAX_WORDS, contract_block
from jobagent.core.models import ContractOffer, ConstraintStatus, SalaryRange, WorkType
from jobagent.core.profile import ProfileError, load_profile
from jobagent.core.rates import find_day_rate
from jobagent.core.scoring import check_constraints, score_fit
from tests.conftest import edit_yaml
from tests.test_scoring import FILTERS, MODEL_ANSWER, FakeClient, constraint, make_jd, make_profile

OFFER = ContractOffer(
    id="interim_em", label="Interim engineering manager",
    detail="Leads a team for a defined period.", evidence=[],
)


def with_offer(profile_factory, floor=None):
    profile = make_profile(profile_factory, FILTERS.model_copy(update={"min_day_rate_aud": floor}))
    profile.assets.contract_offers = [OFFER]
    return profile


def contract(**kw):
    data = dict(work_type=WorkType.contract, salary_range=SalaryRange(raw="Salary undisclosed"))
    data.update(kw)
    return make_jd(**data)


# -- reading a day rate --------------------------------------------------------


@pytest.mark.parametrize("text, low, high, inc", [
    ("$950 per day + Super", 950, 950, False),
    ("up to 1200 Including Super Per Day", 1200, 1200, True),
    ("$1,000 - $1,200 p.d. + super", 1000, 1200, False),
    ("daily rate of $1100", 1100, 1100, None),
    ("$900/day", 900, 900, None),
])
def test_a_stated_rate_is_read(text, low, high, inc):
    rate = find_day_rate(text)
    assert (rate.low, rate.high, rate.includes_super) == (low, high, inc)


@pytest.mark.parametrize("text", [
    "Exceptional Daily Rate",
    "Day Rate: Competitive market rate",
    "a team of 900 engineers with daily standups",
    "$150,000 + super",
    "180K AUD/yr",
])
def test_no_amount_beside_a_per_day_phrase_is_no_rate(text):
    assert find_day_rate(text) is None


# -- the hard filter -----------------------------------------------------------


def test_a_contract_is_asked_for_a_day_rate_not_a_salary_band(profile_factory):
    checks = check_constraints(contract(), with_offer(profile_factory, floor=1000))
    pay = constraint(checks, "day rate")
    assert pay.status is ConstraintStatus.unknown and "day rate" in pay.question
    assert not any(c.name == "salary" for c in checks)


def test_a_rate_below_the_floor_is_a_breach(profile_factory):
    jd = contract(raw_text="Six months. $800 per day.")
    pay = constraint(check_constraints(jd, with_offer(profile_factory, floor=1000)), "day rate")
    assert pay.status is ConstraintStatus.breach


def test_a_rate_straddling_the_floor_is_unknown(profile_factory):
    jd = contract(raw_text="$900 - $1,100 per day")
    pay = constraint(check_constraints(jd, with_offer(profile_factory, floor=1000)), "day rate")
    assert pay.status is ConstraintStatus.unknown


def test_with_no_floor_set_a_rate_is_reported_not_judged(profile_factory):
    jd = contract(raw_text="$600 per day")
    pay = constraint(check_constraints(jd, with_offer(profile_factory)), "day rate")
    assert pay.advisory and "No day-rate floor" in pay.detail


def test_a_fixed_term_role_quoting_a_day_rate_without_a_figure_is_asked_the_day_rate(profile_factory):
    jd = make_jd(work_type=WorkType.fixed_term, salary_range=SalaryRange(raw="Competitive day rate"))
    pay = constraint(check_constraints(jd, with_offer(profile_factory, floor=800)), "day rate")
    assert pay.status is ConstraintStatus.unknown and "$800" in pay.question


def test_a_fixed_term_role_with_an_annual_salary_keeps_the_salary_check(profile_factory):
    jd = make_jd(work_type=WorkType.fixed_term)
    names = {c.name for c in check_constraints(jd, with_offer(profile_factory, floor=1000))}
    assert "salary" in names and "day rate" not in names


# -- scoring -------------------------------------------------------------------


def test_a_contract_ad_gets_the_framing_and_keeps_a_known_offer(profile_factory):
    client = FakeClient({**MODEL_ANSWER, "contract_offer": "interim_em"})
    fit = score_fit(contract(), with_offer(profile_factory), client=client)
    assert "score it the way a contractor is bought" in client.prompt
    assert fit.contract_offer == "interim_em"


def test_an_invented_offer_is_dropped(profile_factory):
    client = FakeClient({**MODEL_ANSWER, "contract_offer": "chief_wizard"})
    assert score_fit(contract(), with_offer(profile_factory), client=client).contract_offer is None


def test_a_permanent_ad_gets_no_framing_and_no_offer(profile_factory):
    client = FakeClient({**MODEL_ANSWER, "contract_offer": "interim_em"})
    fit = score_fit(make_jd(), with_offer(profile_factory), client=client)
    assert "contractor is bought" not in client.prompt and fit.contract_offer is None


# -- writing -------------------------------------------------------------------


def test_the_writer_is_given_the_offer_and_the_letter_is_a_short_note(profile_factory):
    profile = with_offer(profile_factory)
    letter = " ".join(contract_block(profile, "interim_em", letter=True).split())
    assert "Interim engineering manager" in letter
    assert f"under {CONTRACT_NOTE_MAX_WORDS} words" in letter
    assert "cover note" not in contract_block(profile, "interim_em", letter=False)


def test_no_offer_no_block(profile_factory):
    assert contract_block(with_offer(profile_factory), None, letter=True) is None


# -- the profile ---------------------------------------------------------------


def test_an_offer_citing_evidence_the_profile_lacks_is_refused(profile_factory):
    def add(dst):
        edit_yaml(dst / "assets.yaml", lambda data: data.update({"contract_offers": [
            {"id": "x", "label": "X", "detail": "d", "evidence": ["no_such_entry"]}]}))
    with pytest.raises(ProfileError, match="no_such_entry"):
        load_profile(profile_factory(add))
