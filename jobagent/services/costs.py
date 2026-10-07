"""What an action is expected to cost, stated before it is spent.

Measured, never quoted: the figure comes from `runs.jsonl` for the model the
route resolves to right now (research R5). A price quoted from memory or a
constant goes stale the way the hardcoded price table did.

`describe` gives the one line both front ends print, so the CLI and the UI
cannot drift into saying different things about the same money.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jobagent.adapters.llm import CallType, LLMError, resolve_route
from jobagent.adapters.prices import PriceError, load_prices
from jobagent.core.spend import UNKNOWN, SpendError, expected_cost, load_runs
from jobagent.services.workspace import Workspace

_CALL_TYPE = {
    "add_ad": CallType.parse_jd,
    "score": CallType.score,
    "generate": CallType.generate,
    "prep": CallType.prep,
    "classify": CallType.classify,
}

# Each prompt label runs on its own call type's route, which need not be the
# action's: the classifier may be a cheaper model than the writer, and each is
# priced from its own history.
_LABEL_CALL = {
    "parse_jd": CallType.parse_jd,
    "score_fit": CallType.score,
    "generate_resume": CallType.generate,
    "generate_cover_letter": CallType.generate,
    "generate_answers": CallType.generate,
    "interview_prep": CallType.prep,
    "classify_role": CallType.classify,
    "check_claims": CallType.review,
    "review_documents": CallType.review,
}


@dataclass
class CostEstimate:
    model: str | None
    budget: bool
    per_label: dict[str, "tuple[float, int] | str | None"] = field(default_factory=dict)
    route_error: str | None = None

    @property
    def unknown(self) -> bool:
        return any(v == UNKNOWN for v in self.per_label.values())

    @property
    def unmeasured(self) -> list[str]:
        return [label for label, v in self.per_label.items() if v is None]

    @property
    def total_usd(self) -> float | None:
        """The sum, or None if any selected prompt is unknown or unmeasured.

        Never a partial sum: "$0.11" for a resume-plus-letter run whose letter
        has no measurement would understate by half and read as complete.
        """
        if not self.per_label or self.unknown or self.unmeasured:
            return None
        return sum(v[0] for v in self.per_label.values())

    @property
    def samples(self) -> int:
        counts = [v[1] for v in self.per_label.values() if isinstance(v, tuple)]
        return min(counts) if counts else 0


def labels_for(
    action: str,
    *,
    resume=False,
    cover=False,
    answers=False,
    classify=False,
    check_claims=False,
    review=False,
) -> list[str]:
    """The prompt labels an action will run. `classify` adds the role-kind call
    an unclassified ad needs first; the two checks follow generate (spec 003)."""
    first = ["classify_role"] if classify else []
    if action == "add_ad":
        return ["parse_jd"]
    if action == "score":
        return ["score_fit"] + first
    if action == "prep":
        return ["interview_prep"]
    if action == "classify":
        return ["classify_role"]
    if action == "generate":
        prose = cover or answers
        return (
            first
            + (["generate_resume"] if resume else [])
            + (["generate_cover_letter"] if cover else [])
            + (["generate_answers"] if answers else [])
            + (["check_claims"] if check_claims and prose else [])
            + (["review_documents"] if review else [])
        )
    raise ValueError(f"unknown action {action!r}")


def estimate(
    ws: Workspace,
    config,
    action: str,
    *,
    resume=False,
    cover=False,
    answers=False,
    check_claims=False,
    review=False,
    jd_id: int | None = None,
    price_lookup=None,
) -> CostEstimate:
    """Past calls' tokens at today's prices (`prices.yaml`), averaged per action.

    If the price table cannot be read, every label is "unknown" rather than
    falling back to logged costs that are known to be stale. With `jd_id`, a
    score or generate of an ad that has no role kind yet includes the
    classifier's call.
    """
    budget = bool(config.budget_mode)
    classify = False
    if jd_id is not None and action in ("score", "generate"):
        from jobagent.services import role_kind

        try:
            classify = role_kind.needs_classify(ws, jd_id)
        except Exception:  # noqa: BLE001 - an estimate never blocks the work
            classify = False
    labels = labels_for(
        action,
        resume=resume,
        cover=cover,
        answers=answers,
        classify=classify,
        check_claims=check_claims,
        review=review,
    )
    try:
        model = resolve_route(config, _CALL_TYPE[action]).model
        models = {label: resolve_route(config, _LABEL_CALL[label]).model for label in labels}
    except LLMError as exc:
        return CostEstimate(model=None, budget=budget, route_error=str(exc))
    try:
        records = load_runs(ws.runs_log_path)
    except SpendError:
        records = []
    if price_lookup is None:
        try:
            price_lookup = load_prices().lookup
        except PriceError:
            price_lookup = lambda _model: None  # noqa: E731 - every label "unknown"
    per_label = {}
    for label in labels:
        per_label.update(expected_cost(records, [label], models[label], price_lookup))
    return CostEstimate(model=model, budget=budget, per_label=per_label)


def describe(est: CostEstimate) -> str:
    """One line, shown before the call: what it will probably cost, or why it cannot say."""
    if est.route_error:
        return f"No model configured: {est.route_error}"
    if est.budget:
        return f"Free tier (budget mode, {est.model})."
    if est.unknown:
        return f"Price unknown for {est.model}: check prices.yaml."
    if est.unmeasured:
        measured = [v for v in est.per_label.values() if isinstance(v, tuple)]
        if not measured:
            return f"No measurement for {est.model} yet ({', '.join(est.unmeasured)})."
        # Never a partial sum presented as the total: the measured part is
        # stated as such, and what is missing is named.
        part = sum(v[0] for v in measured)
        return (
            f"Expected ~${part:.2f} for what has been measured. "
            f"No measurement yet for {', '.join(est.unmeasured)}."
        )
    total = est.total_usd
    runs = "run" if est.samples == 1 else "runs"
    return f"Expected cost ~${total:.2f} (mean of {est.samples} {runs} on {est.model})."


def label_cost(est: CostEstimate, label: str) -> str:
    """One prompt's expected cost, as shown beside its tick box."""
    if est.route_error:
        return "no model configured"
    if est.budget:
        return "free tier"
    value = est.per_label.get(label)
    if value == UNKNOWN:
        return "price unknown"
    if value is None:
        return "not yet measured"
    return f"~${value[0]:.2f}"
