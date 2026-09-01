"""Measuring the fit scorer against applications with known outcomes.

**What is measured is not whether the employer said yes.** That distinction is
the whole design, and one case forces it: Alan was offered the Easy Signs job
and worked there, and the scorer says *skip* — because the commute to Smeaton
Grange is an absolute filter in his own profile, and it is the reason the role
ended. Scored against "would they hire him", that is a miss, and tuning it
away would teach the scorer to stop raising the constraint that actually
mattered.

So each case carries two labels. ``outcome`` is what happened, recorded
faithfully. ``worth_applying`` is the retrospective judgment — knowing what he
knows now, was that day well spent. The scorer is graded against the second,
and the first is reported beside it as the weaker, noisier signal it is.

Two error costs, and they are not symmetric. A **false positive** — apply on a
role not worth applying to — costs a day of work and a rejection. A **false
negative** — skip a role that was worth it — costs an opportunity that does
not come back. The scorer is deliberately biased toward saying no, so false
negatives are the ones to watch.

Nothing here calls a model or writes to the store.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, field_validator

from jobagent.core.models import FitAssessment, MatchStatus, Verdict

CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "cases.yaml"


class EvalError(Exception):
    """The case set could not be read."""


class Outcome(str, Enum):
    """What actually happened, in rough order of how far it got."""

    not_applied = "not_applied"
    applied_no_reply = "applied_no_reply"
    rejected_screen = "rejected_screen"
    recruiter_call = "recruiter_call"
    interview_1 = "interview_1"
    interview_2 = "interview_2"
    offer = "offer"
    withdrew = "withdrew"


# How far the application got, for the secondary correlation. `withdrew` is
# excluded rather than ranked: Alan stopping is not the employer's verdict.
_OUTCOME_RANK: dict[Outcome, int] = {
    Outcome.not_applied: 0,
    Outcome.applied_no_reply: 1,
    Outcome.rejected_screen: 2,
    Outcome.recruiter_call: 3,
    Outcome.interview_1: 4,
    Outcome.interview_2: 5,
    Outcome.offer: 6,
}


class Worth(str, Enum):
    """Was the day well spent, knowing what he knows now."""

    yes = "yes"
    no = "no"
    unsure = "unsure"


class EvalCase(BaseModel):
    id: str
    jd_id: int
    outcome: Outcome
    worth_applying: Worth = Worth.unsure
    why: str = ""
    # True where the label was inferred from the notes in outcomes.yaml rather
    # than stated by Alan. Reported separately so a metric is never quoted as
    # his judgment when it is a reading of his notes.
    label_derived: bool = False
    file: str = ""

    @field_validator("worth_applying", mode="before")
    @classmethod
    def _tolerate_yaml_booleans(cls, value: object) -> object:
        """YAML 1.1 turns an unquoted `yes` into `True`.

        Rejecting it would be defensible but unhelpful: the intent is never
        ambiguous, and the alternative is Alan debugging a schema error over a
        pair of missing quotes.
        """
        if isinstance(value, bool):
            return Worth.yes if value else Worth.no
        return value


@dataclass
class CaseResult:
    case: EvalCase
    assessment: FitAssessment | None

    @property
    def scored(self) -> bool:
        return self.assessment is not None

    @property
    def applied_verdict(self) -> bool | None:
        """True if the scorer would have had him apply."""
        if self.assessment is None:
            return None
        return self.assessment.verdict is not Verdict.skip

    @property
    def agreement(self) -> str:
        """How the verdict lines up with the retrospective judgment."""
        if self.assessment is None:
            return "unscored"
        if self.case.worth_applying is Worth.unsure:
            return "unlabelled"
        said_apply = self.applied_verdict
        was_worth = self.case.worth_applying is Worth.yes
        if said_apply and was_worth:
            return "agree — apply"
        if not said_apply and not was_worth:
            return "agree — skip"
        if said_apply and not was_worth:
            return "false positive"
        return "false negative"


@dataclass
class EvalReport:
    results: list[CaseResult]

    # Grading against the retrospective judgment.
    agree: int = 0
    false_positives: list[CaseResult] = field(default_factory=list)
    false_negatives: list[CaseResult] = field(default_factory=list)
    unlabelled: int = 0
    unscored: int = 0

    mean_score_worth: float | None = None
    mean_score_not_worth: float | None = None
    separation: float | None = None

    # The secondary, noisier measure.
    outcome_correlation: float | None = None
    derived_labels: int = 0

    @property
    def labelled(self) -> int:
        return self.agree + len(self.false_positives) + len(self.false_negatives)

    @property
    def accuracy(self) -> float | None:
        return self.agree / self.labelled if self.labelled else None


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_cases(path: Path | None = None) -> list[EvalCase]:
    """Read ``evals/cases.yaml``."""
    path = path or CASES_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvalError(f"No case set at {path}.") from exc
    except OSError as exc:
        raise EvalError(f"Could not read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise EvalError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, list):
        raise EvalError(f"{path} must hold a list of cases, got {type(raw).__name__}.")

    cases = []
    for index, entry in enumerate(raw, 1):
        name = entry.get("id", f"#{index}") if isinstance(entry, dict) else f"#{index}"
        try:
            cases.append(EvalCase.model_validate(entry))
        except ValidationError as exc:
            raise EvalError(f"Case {name!r} in {path} is invalid:\n{exc}") from exc

    seen = {case.id for case in cases}
    if len(seen) != len(cases):
        raise EvalError("Two cases share an id.")
    return cases


# --------------------------------------------------------------------------- #
# Grading
# --------------------------------------------------------------------------- #


def build_report(results: list[CaseResult]) -> EvalReport:
    report = EvalReport(results=results)

    for result in results:
        agreement = result.agreement
        if agreement == "unscored":
            report.unscored += 1
        elif agreement == "unlabelled":
            report.unlabelled += 1
        elif agreement == "false positive":
            report.false_positives.append(result)
        elif agreement == "false negative":
            report.false_negatives.append(result)
        else:
            report.agree += 1
        if result.case.label_derived:
            report.derived_labels += 1

    worth = [
        r.assessment.overall_score
        for r in results
        if r.scored and r.case.worth_applying is Worth.yes
    ]
    not_worth = [
        r.assessment.overall_score
        for r in results
        if r.scored and r.case.worth_applying is Worth.no
    ]
    if worth:
        report.mean_score_worth = statistics.fmean(worth)
    if not_worth:
        report.mean_score_not_worth = statistics.fmean(not_worth)
    if worth and not_worth:
        report.separation = report.mean_score_worth - report.mean_score_not_worth

    report.outcome_correlation = _outcome_correlation(results)
    return report


def _outcome_correlation(results: list[CaseResult]) -> float | None:
    """Spearman rank correlation between score and how far the application got.

    Reported as the weaker measure and never on its own. It rewards a scorer
    for predicting the employer's behaviour, which is not the job — the Easy
    Signs case scores badly here and is right.
    """
    pairs = [
        (r.assessment.overall_score, _OUTCOME_RANK[r.case.outcome])
        for r in results
        if r.scored and r.case.outcome in _OUTCOME_RANK
    ]
    if len(pairs) < 3:
        return None

    scores = _ranks([p[0] for p in pairs])
    outcomes = _ranks([p[1] for p in pairs])
    return _pearson(scores, outcomes)


def _ranks(values: list[float]) -> list[float]:
    """Fractional ranks, ties sharing the average of the positions they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        average = (index + end) / 2 + 1
        for position in range(index, end + 1):
            ranks[order[position]] = average
        index = end + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denominator = (sum(v * v for v in dx) * sum(v * v for v in dy)) ** 0.5
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denominator


# --------------------------------------------------------------------------- #
# Prompt regression
# --------------------------------------------------------------------------- #


@dataclass
class RunDiff:
    """What changed for one case between two scoring runs."""

    case_id: str
    before: FitAssessment
    after: FitAssessment

    @property
    def verdict_changed(self) -> bool:
        return self.before.verdict is not self.after.verdict

    @property
    def score_delta(self) -> int:
        return self.after.overall_score - self.before.overall_score

    @property
    def screen_delta(self) -> int:
        return self.after.recruiter_screen_score - self.before.recruiter_screen_score

    @property
    def requirement_delta(self) -> int:
        return len(self.after.requirements) - len(self.before.requirements)

    @property
    def met_delta(self) -> int:
        return _met(self.after) - _met(self.before)

    @property
    def changed(self) -> bool:
        return bool(
            self.verdict_changed
            or self.score_delta
            or self.screen_delta
            or self.requirement_delta
            or self.met_delta
        )


def diff_runs(case_id: str, history: list[FitAssessment]) -> RunDiff | None:
    """Compare the two most recent assessments for one case, newest first."""
    if len(history) < 2:
        return None
    return RunDiff(case_id=case_id, before=history[1], after=history[0])


def _met(assessment: FitAssessment) -> int:
    return sum(1 for r in assessment.requirements if r.status is MatchStatus.met)
