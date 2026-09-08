"""`jobagent spend` — attributing the API bill to the work that caused it.

The run log recorded the prompt name and nothing else, so it could say how much
went on scoring and could not say what one application cost, or whether a
month's spend was real work or eval runs. These tests cover the fields that
answer those questions, and the join that makes the parse call attributable at
all: `jd add` parses an ad before the JD has an id.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.adapters.llm import RunContext, log_attribution
from jobagent.cli import spend as spend_cli
from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core.spend import SpendError, build_report, load_runs
from tests.test_llm import FakeClient

runner = CliRunner()


def flat(output: str) -> str:
    """Collapse rich's wrapping, so an assertion is about the words printed and
    not the width of the terminal the test happened to run in."""
    return " ".join(output.split())


def call(**fields) -> dict:
    record = {
        "ts": 1_756_000_000.0,
        "label": "score_fit",
        "model": "claude-sonnet-5",
        "provider": "anthropic",
        "input_tokens": 1000,
        "output_tokens": 100,
        "cost_usd": 0.003,
        "price_unknown": False,
        "truncated": False,
        "command": "score",
        "jd_id": 1,
        "source": "cli",
        "run_id": "aaaa",
    }
    record.update(fields)
    return record


def write_log(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "runs.jsonl"
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )
    return path


def group(report, breakdown: str, key: str):
    return next(g for g in getattr(report, breakdown) if g.key == key)


# --------------------------------------------------------------------------- #
# Reading the log
# --------------------------------------------------------------------------- #


def test_a_missing_log_is_reported(tmp_path: Path) -> None:
    with pytest.raises(SpendError, match="Nothing has been spent"):
        load_runs(tmp_path / "runs.jsonl")


def test_a_half_written_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    """The log is appended to inside an `except OSError: pass`, so a truncated
    final line is a normal thing to find after a crash. Losing one call's cost
    beats refusing to report at all."""
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps(call()) + '\n{"ts": 1, "lab\n', encoding="utf-8")

    assert len(load_runs(path)) == 1


# --------------------------------------------------------------------------- #
# Attribution — the reason `run_id` exists
# --------------------------------------------------------------------------- #


def test_a_parse_call_is_attributed_through_its_run(tmp_path: Path) -> None:
    """`jd add` parses the ad before the store has assigned an id, so the call
    is logged without one. The attribution record is what connects them."""
    records = load_runs(
        write_log(
            tmp_path,
            [
                call(label="parse_jd", command="jd add", jd_id=None, run_id="r1"),
                {"ts": 1.0, "type": "attribution", "run_id": "r1", "jd_id": 42},
            ],
        )
    )

    report = build_report(records)

    assert group(report, "by_jd", "JD 42").calls == 1
    assert not [g for g in report.by_jd if g.key == "(no JD)"]


def test_an_attribution_record_is_not_counted_as_a_call(tmp_path: Path) -> None:
    records = load_runs(
        write_log(
            tmp_path,
            [call(), {"ts": 1.0, "type": "attribution", "run_id": "aaaa", "jd_id": 7}],
        )
    )

    assert build_report(records).calls == 1


def test_a_recorded_jd_id_wins_over_the_join(tmp_path: Path) -> None:
    records = load_runs(
        write_log(
            tmp_path,
            [
                call(jd_id=5, run_id="r1"),
                {"ts": 1.0, "type": "attribution", "run_id": "r1", "jd_id": 42},
            ],
        )
    )

    assert group(build_report(records), "by_jd", "JD 5").calls == 1


def test_an_unattributable_call_is_shown_not_dropped() -> None:
    """Every record in the log predates these fields. They still cost money."""
    report = build_report([call(jd_id=None, run_id="unmatched")])

    assert group(report, "by_jd", "(no JD)").calls == 1


# --------------------------------------------------------------------------- #
# The questions the log could not answer before
# --------------------------------------------------------------------------- #


def test_spend_is_split_between_real_work_and_grading(tmp_path: Path) -> None:
    """$18.51 in the log, and no way to tell how much of it was eval runs."""
    records = load_runs(
        write_log(
            tmp_path,
            [
                call(source="cli", cost_usd=1.0),
                call(source="eval", cost_usd=0.25),
                call(source="eval", cost_usd=0.25),
            ],
        )
    )

    report = build_report(records)

    assert group(report, "by_source", "cli").cost_usd == pytest.approx(1.0)
    assert group(report, "by_source", "eval").cost_usd == pytest.approx(0.5)


def test_records_written_before_source_existed_count_as_real_work() -> None:
    """Calling them "unknown" would put the whole history in a bucket that
    means nothing. They were real applications."""
    report = build_report([{"ts": 1.0, "cost_usd": 1.0, "model": "m"}])

    assert group(report, "by_source", "cli").calls == 1


def test_one_application_can_be_costed_end_to_end(tmp_path: Path) -> None:
    records = load_runs(
        write_log(
            tmp_path,
            [
                call(jd_id=22, label="parse_jd", cost_usd=0.08),
                call(jd_id=22, label="score_fit", cost_usd=0.20),
                call(jd_id=22, label="generate_resume", cost_usd=0.30),
                call(jd_id=23, label="score_fit", cost_usd=0.20),
            ],
        )
    )

    report = build_report(records, jd_id=22)

    assert report.total_usd == pytest.approx(0.58)
    assert report.calls == 3


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


def test_filtering_by_model(tmp_path: Path) -> None:
    records = load_runs(
        write_log(
            tmp_path,
            [call(model="claude-sonnet-5"), call(model="gemini-2.5-flash")],
        )
    )

    report = build_report(records, model="gemini")

    assert report.calls == 1
    assert report.models == ("gemini-2.5-flash",)


def test_filtering_by_date(tmp_path: Path) -> None:
    records = load_runs(
        write_log(tmp_path, [call(ts=1000.0), call(ts=3000.0)])
    )

    assert build_report(records, since=2000.0).calls == 1


def test_filtering_by_source(tmp_path: Path) -> None:
    records = load_runs(
        write_log(tmp_path, [call(source="cli"), call(source="eval")])
    )

    assert build_report(records, source="eval").calls == 1


# --------------------------------------------------------------------------- #
# Saying what was read, and what could not be priced
# --------------------------------------------------------------------------- #


def test_a_mixed_model_total_is_flagged(tmp_path: Path) -> None:
    """CLAUDE.md: anything reading a run history says which model it read.
    Prices differ fivefold, so a mixed total is not one number."""
    records = load_runs(
        write_log(tmp_path, [call(model="claude-sonnet-5"), call(model="claude-opus-5")])
    )

    report = build_report(records)

    assert report.mixed_models
    assert report.models == ("claude-opus-5", "claude-sonnet-5")


def test_a_single_model_total_is_not_flagged(tmp_path: Path) -> None:
    records = load_runs(write_log(tmp_path, [call(), call()]))

    assert not build_report(records).mixed_models


def test_unpriced_calls_are_counted_out_of_the_total(tmp_path: Path) -> None:
    records = load_runs(
        write_log(
            tmp_path,
            [call(cost_usd=1.0), call(cost_usd=None, price_unknown=True)],
        )
    )

    report = build_report(records)

    assert report.total_usd == pytest.approx(1.0)
    assert report.unpriced_calls == 1


def test_an_old_null_cost_counts_as_unpriced(tmp_path: Path) -> None:
    """`price_unknown` is newer than the log. A null cost in a record without
    the field means the same thing."""
    report = build_report([{"ts": 1.0, "model": "m", "cost_usd": None}])

    assert report.unpriced_calls == 1


# --------------------------------------------------------------------------- #
# Repricing — the log holds what a call was costed at, which may have been wrong
# --------------------------------------------------------------------------- #


def test_the_logged_total_is_compared_with_todays_prices(tmp_path: Path) -> None:
    """Every Sonnet record before 2026-09-08 was costed at $3/$15 when the rate
    is $2/$10. The report shows both rather than choosing: whether the price
    changed or the table was wrong is not something the log can know."""
    records = load_runs(
        write_log(
            tmp_path,
            [call(input_tokens=1_000_000, output_tokens=0, cost_usd=3.0)],
        )
    )

    report = build_report(records, price_lookup=lambda m: (2.0, 10.0))

    assert report.total_usd == pytest.approx(3.0)
    assert report.repriced_usd == pytest.approx(2.0)
    assert report.repricing_gap == pytest.approx(1 / 3)


def test_no_price_lookup_means_no_comparison(tmp_path: Path) -> None:
    report = build_report(load_runs(write_log(tmp_path, [call()])))

    assert report.repriced_usd is None
    assert report.repricing_gap is None


# --------------------------------------------------------------------------- #
# End to end: what the client writes is what the report reads
# --------------------------------------------------------------------------- #


def test_the_client_records_the_context_it_was_given(tmp_path: Path) -> None:
    log = tmp_path / "runs.jsonl"
    client = FakeClient(
        ["a"],
        model="claude-sonnet-5",
        runs_log_path=log,
        context=RunContext(command="score", jd_id=22),
    )

    client.complete(prompt="x", label="score_fit")

    record = json.loads(log.read_text(encoding="utf-8").strip())
    assert record["command"] == "score"
    assert record["jd_id"] == 22
    assert record["source"] == "cli"
    assert record["run_id"] == client.context.run_id


def test_a_parse_then_attribution_round_trips(tmp_path: Path) -> None:
    """The whole `jd add` path: parse with no id, store, attribute, report."""
    log = tmp_path / "runs.jsonl"
    client = FakeClient(
        ["a"], model="claude-sonnet-5", runs_log_path=log,
        context=RunContext(command="jd add"),
    )

    client.complete(prompt="x", label="parse_jd")
    log_attribution(log, client.context.run_id, jd_id=99)

    report = build_report(load_runs(log))

    assert group(report, "by_jd", "JD 99").calls == 1
    assert group(report, "by_command", "jd add").calls == 1


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


@pytest.fixture
def wired(tmp_path, monkeypatch):
    log = write_log(
        tmp_path,
        [
            call(jd_id=22, label="parse_jd", cost_usd=0.08),
            call(jd_id=22, label="score_fit", cost_usd=0.20),
        ],
    )
    config = Config(
        _env_file=None, db_path=tmp_path / "jobagent.db", runs_log_path=log
    )
    monkeypatch.setattr(spend_cli, "get_config", lambda: config)
    return config


def test_spend_reports_the_total_and_the_breakdowns(wired) -> None:
    result = runner.invoke(app, ["spend"])

    assert result.exit_code == 0
    output = flat(result.stdout)
    assert "$0.28 over 2 call(s)" in output
    assert "JD 22" in output
    assert "score_fit" in output


def test_spend_names_the_model_it_read(wired) -> None:
    result = runner.invoke(app, ["spend"])

    assert "claude-sonnet-5" in flat(result.stdout)


def test_spend_filters_to_one_jd(wired) -> None:
    result = runner.invoke(app, ["spend", "--jd", "999"])

    assert result.exit_code == 0
    assert "No calls match" in flat(result.stdout)


def test_spend_rejects_a_malformed_date(wired) -> None:
    result = runner.invoke(app, ["spend", "--since", "last tuesday"])

    assert result.exit_code == 2
    assert "YYYY-MM-DD" in flat(result.stderr)


def test_spend_costs_nothing(wired, monkeypatch) -> None:
    """It reads a file. A report that spends money is not a report."""
    def explode(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("spend must not build a model client")

    monkeypatch.setattr("jobagent.adapters.llm.get_client", explode)

    assert runner.invoke(app, ["spend"]).exit_code == 0
