"""Every paid CLI command states its expected cost before it spends. No network.

Each test lets the command get as far as the model call, then stops it there,
and checks the estimate had already been printed with the right selection.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.cli import estimate as estimate_cli
from jobagent.cli import generate as generate_cli
from jobagent.cli import jd as jd_cli
from jobagent.cli import prep as prep_cli
from jobagent.cli import score as score_cli
from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import FitAssessment, JobDescription, Verdict, WorkArrangement, WorkType

runner = CliRunner()
EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
MODEL = "claude-sonnet-5"


class Stop(Exception):
    """Raised in place of the model call."""


@pytest.fixture
def config(tmp_path):
    runs_log = tmp_path / "runs.jsonl"
    runs_log.write_text(
        json.dumps({"label": "score_fit", "model": MODEL, "input_tokens": 1000,
                    "output_tokens": 100, "cost_usd": 0.1, "price_unknown": False,
                    "run_id": "a", "outcome": "ok"}) + "\n"
    )
    return Config(
        _env_file=None,
        db_path=tmp_path / "jobagent.db",
        runs_log_path=runs_log,
        output_dir=tmp_path / "out",
        jd_dir=tmp_path / "jds",
        profile_dir=EXAMPLE_PROFILE,
        llm_default=f"anthropic:{MODEL}",
    )


@pytest.fixture
def printed(monkeypatch):
    calls = []
    for module in (jd_cli, score_cli, generate_cli, prep_cli):
        monkeypatch.setattr(module, "print_estimate", lambda cfg, action, **kw: calls.append((action, kw)))
    return calls


def seed(config, verdict=Verdict.apply) -> int:
    with store.open_store(config.db_path) as conn:
        jd_id = store.add_jd(conn, JobDescription(
            title="Engineering Manager", company="Acme Logistics",
            work_type=WorkType.permanent, work_arrangement=WorkArrangement.hybrid,
            raw_text="An invented advertisement. " * 60,
            ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        ))
        store.add_assessment(conn, FitAssessment(
            jd_id=jd_id, overall_score=70, recruiter_screen_score=60, verdict=verdict,
            rationale="Invented.", target_role_match=True, target_role_note="Invented.",
            scored_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        ))
    return jd_id


def stop_at(monkeypatch, module, name, printed):
    def model_call(*args, **kwargs):
        assert printed, "the model was reached before the estimate was printed"
        raise Stop
    monkeypatch.setattr(module, name, model_call)
    monkeypatch.setattr(module, "get_client", lambda *a, **k: object())


def test_score(config, monkeypatch, printed):
    monkeypatch.setattr(score_cli, "get_config", lambda: config)
    stop_at(monkeypatch, score_cli, "score_fit", printed)
    runner.invoke(app, ["score", str(seed(config))])
    assert printed == [("score", {})]


def test_generate(config, monkeypatch, printed):
    monkeypatch.setattr(generate_cli, "get_config", lambda: config)
    stop_at(monkeypatch, generate_cli, "build_resume", printed)
    runner.invoke(app, ["generate", str(seed(config)), "--resume", "--cover"])
    assert printed == [("generate", {"resume": True, "cover": True, "answers": False})]


def test_prep(config, monkeypatch, printed):
    monkeypatch.setattr(prep_cli, "get_config", lambda: config)
    stop_at(monkeypatch, prep_cli, "prepare", printed)
    runner.invoke(app, ["prep", str(seed(config))])
    assert printed == [("prep", {})]


def test_jd_add(config, monkeypatch, printed, tmp_path):
    monkeypatch.setattr(jd_cli, "get_config", lambda: config)
    stop_at(monkeypatch, jd_cli, "parse_jd", printed)
    ad = tmp_path / "ad.txt"
    ad.write_text("An invented advertisement. " * 60)
    runner.invoke(app, ["jd", "add", "--file", str(ad)])
    assert printed == [("add_ad", {})]


def test_the_line_itself(config, capsys):
    estimate_cli.print_estimate(config, "score")
    assert "Expected cost ~$" in capsys.readouterr().err


def test_a_failed_estimate_never_blocks(config, monkeypatch, capsys):
    def broken(*a, **k):
        raise RuntimeError("log unreadable")
    monkeypatch.setattr(estimate_cli.costs, "estimate", broken)
    estimate_cli.print_estimate(config, "score")
    assert "Could not estimate the cost: log unreadable" in capsys.readouterr().err
