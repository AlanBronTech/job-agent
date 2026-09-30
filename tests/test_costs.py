"""services.costs: the estimate and the line that states it."""

from __future__ import annotations

import json

import pytest

from jobagent.config import Config
from jobagent.services import costs
from tests.ui_seed import workspace

MODEL = "claude-sonnet-5"


def config(tmp_path, **extra) -> Config:
    return Config(_env_file=None, db_path=tmp_path / "db", llm_default=f"anthropic:{MODEL}", **extra)


def write_log(ws, *records):
    with open(ws.runs_log_path, "w") as handle:
        for r in records:
            handle.write(json.dumps(r) + "\n")


# A fixed table: $1 per million input tokens, nothing for output, so a call
# with N thousand input tokens costs N/1000 dollars.
PRICES = {MODEL: (1.0, 0.0)}


def lookup(model):
    return next((p for m, p in PRICES.items() if m in model), None)


def call(label, cost, run_id, model=MODEL):
    """A logged call. `cost` sets its tokens; None means the model is unpriced."""
    return {"label": label, "model": model if cost is not None else "unpriced-model",
            "input_tokens": int((cost or 0) * 1_000_000), "output_tokens": 0,
            "cost_usd": 99.0, "price_unknown": False, "run_id": run_id, "outcome": "ok"}


def estimate(ws, cfg, action, **kw):
    return costs.estimate(ws, cfg, action, price_lookup=lookup, **kw)


def test_score(tmp_path):
    ws = workspace(tmp_path)
    write_log(ws, call("score_fit", 0.10, "a"), call("score_fit", 0.12, "b"))
    est = estimate(ws, config(tmp_path), "score")
    assert est.total_usd == pytest.approx(0.11)
    assert costs.describe(est) == f"Expected cost ~$0.11 (mean of 2 runs on {MODEL})."


def test_generate_sums_only_what_is_selected(tmp_path):
    ws = workspace(tmp_path)
    write_log(
        ws,
        call("generate_resume", 0.08, "a"),
        call("generate_cover_letter", 0.05, "a"),
        call("generate_answers", 0.04, "a"),
    )
    est = estimate(ws, config(tmp_path), "generate", resume=True, cover=True)
    assert est.total_usd == pytest.approx(0.13)


def test_a_missing_measurement_is_never_a_partial_sum(tmp_path):
    ws = workspace(tmp_path)
    write_log(ws, call("generate_resume", 0.08, "a"))
    est = estimate(ws, config(tmp_path), "generate", resume=True, cover=True)
    assert est.total_usd is None
    assert "No measurement" in costs.describe(est) and "generate_cover_letter" in costs.describe(est)


def test_unpriced_is_unknown_not_zero(tmp_path):
    ws = workspace(tmp_path)
    write_log(ws, call("score_fit", None, "a"))
    # The unpriced call is on another model, so give the route that model.
    est = estimate(ws, Config(_env_file=None, db_path=tmp_path / "db",
                              llm_default="anthropic:unpriced-model"), "score")
    assert est.total_usd is None
    assert costs.describe(est).startswith("Price unknown")


def test_no_log_yet(tmp_path):
    est = estimate(workspace(tmp_path), config(tmp_path), "prep")
    assert costs.describe(est).startswith("No measurement")


def test_budget_mode(tmp_path):
    est = costs.estimate(workspace(tmp_path), config(tmp_path, budget_mode=True), "score")
    assert costs.describe(est).startswith("Free tier")


def test_no_model_configured(tmp_path):
    est = costs.estimate(workspace(tmp_path), Config(_env_file=None, db_path=tmp_path / "db"), "score")
    assert costs.describe(est).startswith("No model configured")


def test_logged_cost_is_ignored_in_favour_of_todays_price(tmp_path):
    ws = workspace(tmp_path)
    write_log(ws, call("score_fit", 0.11, "a"))  # logged at $99, priced now at $0.11
    assert estimate(ws, config(tmp_path), "score").total_usd == pytest.approx(0.11)
