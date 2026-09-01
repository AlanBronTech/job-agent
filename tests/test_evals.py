"""Unit tests for the eval harness.

The measurement design is the thing under test. One case decides it: Alan was
offered the Easy Signs job and the scorer says skip, because the commute is an
absolute filter in his own profile and is the reason the role ended. A harness
that grades on "was he hired" calls that a miss and would tune away the
constraint that mattered.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from jobagent.core.evals import (
    CaseResult,
    EvalCase,
    EvalError,
    Outcome,
    Worth,
    build_report,
    diff_runs,
    load_cases,
)
from jobagent.core.models import (
    FitAssessment,
    MatchStatus,
    RequirementMatch,
    Verdict,
)

SCORED_AT = datetime(2026, 9, 1, tzinfo=timezone.utc)


def case(**overrides) -> EvalCase:
    data = {
        "id": "toshiba",
        "jd_id": 12,
        "outcome": Outcome.interview_2,
        "worth_applying": Worth.yes,
        "why": "Two interviews on a genuine EM role.",
    }
    data.update(overrides)
    return EvalCase(**data)


def assessment(**overrides) -> FitAssessment:
    data = {
        "jd_id": 12,
        "overall_score": 62,
        "recruiter_screen_score": 50,
        "verdict": Verdict.apply_with_caveats,
        "rationale": "On target.",
        "target_role_match": True,
        "target_role_note": "Engineering Manager.",
        "scored_at": SCORED_AT,
    }
    data.update(overrides)
    return FitAssessment(**data)


def result(case_kwargs=None, assessment_kwargs=None) -> CaseResult:
    return CaseResult(
        case=case(**(case_kwargs or {})),
        assessment=assessment(**(assessment_kwargs or {})),
    )


# --------------------------------------------------------------------------- #
# Agreement — graded against "was this worth applying to"
# --------------------------------------------------------------------------- #


def test_apply_on_a_role_worth_applying_to_agrees() -> None:
    assert result().agreement == "agree — apply"


def test_skip_on_a_role_not_worth_applying_to_agrees() -> None:
    assert result(
        {"worth_applying": Worth.no}, {"verdict": Verdict.skip}
    ).agreement == "agree — skip"


def test_apply_with_caveats_counts_as_apply() -> None:
    """It still costs the day. Only `skip` avoids the work."""
    assert result({"worth_applying": Worth.no}).agreement == "false positive"


def test_skip_on_a_role_that_was_worth_it_is_a_false_negative() -> None:
    assert result(
        {"worth_applying": Worth.yes}, {"verdict": Verdict.skip}
    ).agreement == "false negative"


def test_an_unsure_case_is_reported_but_not_graded() -> None:
    assert result({"worth_applying": Worth.unsure}).agreement == "unlabelled"


def test_an_unscored_case_is_reported_but_not_graded() -> None:
    assert CaseResult(case=case(), assessment=None).agreement == "unscored"


def test_the_easy_signs_shape_is_scored_as_agreement_not_a_miss() -> None:
    """Offered the job, and skipping was still the right call — the commute
    that ended it is an absolute filter in his own profile."""
    easy_signs = result(
        {"id": "easy_signs", "outcome": Outcome.offer, "worth_applying": Worth.no},
        {"verdict": Verdict.skip, "overall_score": 58},
    )

    assert easy_signs.agreement == "agree — skip"


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #


def test_the_report_counts_each_kind_of_error() -> None:
    report = build_report(
        [
            result(),                                                    # agree
            result({"id": "a", "worth_applying": Worth.no},
                   {"verdict": Verdict.skip}),                           # agree
            result({"id": "b", "worth_applying": Worth.no}),             # false pos
            result({"id": "c", "worth_applying": Worth.yes},
                   {"verdict": Verdict.skip}),                           # false neg
            result({"id": "d", "worth_applying": Worth.unsure}),         # unlabelled
            CaseResult(case=case(id="e"), assessment=None),              # unscored
        ]
    )

    assert report.agree == 2
    assert len(report.false_positives) == 1
    assert len(report.false_negatives) == 1
    assert report.unlabelled == 1
    assert report.unscored == 1
    assert report.labelled == 4
    assert report.accuracy == 0.5


def test_separation_measures_whether_the_score_discriminates() -> None:
    report = build_report(
        [
            result({"id": "a", "worth_applying": Worth.yes}, {"overall_score": 80}),
            result({"id": "b", "worth_applying": Worth.yes}, {"overall_score": 70}),
            result({"id": "c", "worth_applying": Worth.no}, {"overall_score": 30}),
        ]
    )

    assert report.mean_score_worth == 75
    assert report.mean_score_not_worth == 30
    assert report.separation == 45


def test_derived_labels_are_counted_separately() -> None:
    """A metric must never be quoted as Alan's judgment when it is a reading
    of his notes."""
    report = build_report(
        [
            result({"id": "a", "label_derived": True}),
            result({"id": "b", "label_derived": False}),
        ]
    )

    assert report.derived_labels == 1


def test_outcome_correlation_needs_at_least_three_cases() -> None:
    report = build_report([result(), result({"id": "b"})])

    assert report.outcome_correlation is None


def test_outcome_correlation_is_positive_when_scores_track_outcomes() -> None:
    report = build_report(
        [
            result({"id": "a", "outcome": Outcome.offer}, {"overall_score": 90}),
            result({"id": "b", "outcome": Outcome.interview_2}, {"overall_score": 70}),
            result({"id": "c", "outcome": Outcome.applied_no_reply}, {"overall_score": 20}),
        ]
    )

    assert report.outcome_correlation == pytest.approx(1.0)


def test_a_withdrawn_case_is_left_out_of_the_correlation() -> None:
    """Alan stopping is not the employer's verdict."""
    report = build_report(
        [
            result({"id": "a", "outcome": Outcome.offer}, {"overall_score": 90}),
            result({"id": "b", "outcome": Outcome.interview_2}, {"overall_score": 70}),
            result({"id": "c", "outcome": Outcome.applied_no_reply}, {"overall_score": 20}),
            result({"id": "d", "outcome": Outcome.withdrew}, {"overall_score": 5}),
        ]
    )

    assert report.outcome_correlation == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def test_the_shipped_snapshot_parses() -> None:
    """`evals/cases.yaml` is an export of Alan's pipeline, so its contents are
    his data and change as he records outcomes. All this asserts is that the
    file in the repository still loads — the Easy Signs *shape* is tested
    synthetically above, where it cannot go stale."""
    cases = load_cases()

    assert cases
    assert all(case.jd_id > 0 for case in cases)


def test_unquoted_yaml_booleans_are_tolerated(tmp_path: Path) -> None:
    """YAML 1.1 turns an unquoted `yes` into True. Failing over a pair of
    missing quotes helps nobody."""
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: a\n  jd_id: 1\n  outcome: offer\n  worth_applying: yes\n"
        "- id: b\n  jd_id: 2\n  outcome: offer\n  worth_applying: no\n"
    )

    cases = load_cases(path)

    assert cases[0].worth_applying is Worth.yes
    assert cases[1].worth_applying is Worth.no


def test_a_bad_case_names_itself(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("- id: findex\n  jd_id: 1\n  outcome: hired_immediately\n")

    with pytest.raises(EvalError, match="findex"):
        load_cases(path)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: a\n  jd_id: 1\n  outcome: offer\n- id: a\n  jd_id: 2\n  outcome: offer\n"
    )

    with pytest.raises(EvalError, match="share an id"):
        load_cases(path)


def test_a_missing_case_set_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(EvalError, match="No case set"):
        load_cases(tmp_path / "nope.yaml")


# --------------------------------------------------------------------------- #
# Prompt regression
# --------------------------------------------------------------------------- #


def test_a_case_scored_once_has_nothing_to_diff() -> None:
    assert diff_runs("toshiba", [assessment()]) is None


def test_the_diff_reports_what_moved() -> None:
    newest = assessment(
        overall_score=70,
        recruiter_screen_score=55,
        verdict=Verdict.apply,
        requirements=[
            RequirementMatch(requirement="a", status=MatchStatus.met, note="n"),
            RequirementMatch(requirement="b", status=MatchStatus.gap, note="n"),
        ],
    )
    older = assessment(
        overall_score=62,
        recruiter_screen_score=50,
        verdict=Verdict.apply_with_caveats,
        requirements=[RequirementMatch(requirement="a", status=MatchStatus.gap, note="n")],
    )

    change = diff_runs("toshiba", [newest, older])

    assert change.verdict_changed is True
    assert change.score_delta == 8
    assert change.screen_delta == 5
    assert change.requirement_delta == 1
    assert change.met_delta == 1
    assert change.changed is True


def test_an_identical_rerun_shows_no_change() -> None:
    change = diff_runs("toshiba", [assessment(), assessment()])

    assert change.changed is False


# --------------------------------------------------------------------------- #
# Building the case set from the pipeline
# --------------------------------------------------------------------------- #


def application(jd_id: int, **overrides):
    from datetime import datetime, timezone

    from jobagent.core.models import Application, ApplicationStatus

    data = {
        "jd_id": jd_id,
        "status": ApplicationStatus.interview_2,
        "worth_applying": Worth.yes,
        "worth_why": "Two interviews.",
        "updated_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return Application(**data)


def test_a_finished_application_becomes_a_case() -> None:
    from jobagent.core.evals import cases_from_applications

    cases = cases_from_applications(
        [application(12)], {12: "Engineering Manager"}
    )

    assert len(cases) == 1
    assert cases[0].jd_id == 12
    assert cases[0].outcome is Outcome.interview_2
    assert cases[0].worth_applying is Worth.yes
    assert cases[0].id == "12_engineering_manager"


def test_an_application_still_in_flight_is_left_out() -> None:
    """Grading a scorer on a case that has not finished happening rewards it
    for nothing."""
    from jobagent.core.evals import cases_from_applications
    from jobagent.core.models import ApplicationStatus

    cases = cases_from_applications(
        [
            application(1, status=ApplicationStatus.identified),
            application(2, status=ApplicationStatus.applied),
            application(3, status=ApplicationStatus.applied_no_reply),
        ],
        {},
    )

    assert [case.jd_id for case in cases] == [3]


def test_the_derived_marker_carries_into_the_case() -> None:
    from jobagent.core.evals import cases_from_applications

    cases = cases_from_applications([application(12, worth_derived=True)], {})

    assert cases[0].label_derived is True


def test_a_case_id_survives_an_awkward_title() -> None:
    from jobagent.core.evals import cases_from_applications

    cases = cases_from_applications(
        [application(9)], {9: "Manager, Software Engineering (Client-Facing)!!"}
    )

    assert cases[0].id == "9_manager_software_engineering_cli"


# --------------------------------------------------------------------------- #
# Overrides — the standing disagreement, counted
# --------------------------------------------------------------------------- #


def test_an_override_is_counted() -> None:
    """Whether Alan can overrule the scorer is not the question — he
    obviously can. Who turns out to be right is, and that needs counting."""
    report = build_report(
        [
            result({"id": "a", "overrode_scorer": True, "worth_applying": Worth.yes},
                   {"verdict": Verdict.skip}),
            result({"id": "b", "overrode_scorer": True, "worth_applying": Worth.no},
                   {"verdict": Verdict.skip}),
            result({"id": "c"}),
        ]
    )

    assert len(report.overrides) == 2
    assert report.overrides_vindicated == 1


def test_an_unsettled_override_is_counted_but_not_scored() -> None:
    report = build_report(
        [result({"overrode_scorer": True, "worth_applying": Worth.unsure})]
    )

    assert len(report.overrides) == 1
    assert report.overrides_vindicated == 0


def test_the_override_flag_carries_from_the_pipeline() -> None:
    from jobagent.core.evals import cases_from_applications

    cases = cases_from_applications([application(12, overrode_scorer=True)], {})

    assert cases[0].overrode_scorer is True
