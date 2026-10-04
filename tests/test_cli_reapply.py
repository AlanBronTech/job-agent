"""The CLI side of the six-month rule: messages, --overrule-reapply, jd same.

No network: the model is never reached, because every refusal comes first,
and an overruled or cleared run stops at the next gate (missing profile or
a booby-trapped client).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.cli import generate as generate_cli
from jobagent.cli import jd as jd_cli
from jobagent.cli import score as score_cli
from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import ApplicationStatus, OutsideApplication
from jobagent.services import documents, scoring
from tests.ui_seed import assessment, jd
from jobagent.core.models import Verdict

runner = CliRunner()
EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
NOW = datetime.now(timezone.utc)


def flat(result) -> str:
    return " ".join(result.output.split())


@pytest.fixture
def config(tmp_path, monkeypatch):
    cfg = Config(_env_file=None, db_path=tmp_path / "db", output_dir=tmp_path / "out",
                 profile_dir=EXAMPLE_PROFILE, llm_default="anthropic:claude-sonnet-5")
    for module in (score_cli, generate_cli, jd_cli):
        monkeypatch.setattr(module, "get_config", lambda: cfg)

    def no_client(*a, **k):
        raise AssertionError("reached the model")

    monkeypatch.setattr(score_cli, "get_client", no_client)
    monkeypatch.setattr(scoring, "get_client", no_client)
    monkeypatch.setattr(documents, "get_client", no_client)
    return cfg


def add_ad(cfg, req=None, scored=True):
    with store.open_store(cfg.db_path) as conn:
        ad = jd("Engineering Manager", "Fabrikam Medical", 30)
        ad.requisition_id = req
        jd_id = store.add_jd(conn, ad)
        if scored:
            store.add_assessment(conn, assessment(jd_id, Verdict.apply, 70, 60))
    return jd_id


def add_outside(cfg, days_ago, req=None):
    with store.open_store(cfg.db_path) as conn:
        store.add_outside(conn, OutsideApplication(
            company="Fabrikam Medical", title="Engineering Manager", requisition_id=req,
            applied_on=date.today() - timedelta(days=days_ago),
            status=ApplicationStatus.applied_no_reply, created_at=NOW))


def test_same_job_is_refused_with_the_overrule_command(config):
    add_outside(config, 120, req="JR_000123")
    jd_id = add_ad(config, req="JR_000123")
    result = runner.invoke(app, ["score", str(jd_id)])
    assert result.exit_code == 2
    text = flat(result)
    assert "Same job you applied for on" in text and "120 days ago" in text
    assert "requisition JR_000123" in text and "Nothing was spent" in text
    assert f"jobagent score {jd_id} --overrule-reapply" in text


def test_overrule_is_recorded_and_lets_it_through_to_the_next_gate(config):
    add_outside(config, 120, req="JR_000123")
    jd_id = add_ad(config, req="JR_000123")
    result = runner.invoke(app, ["score", str(jd_id), "--overrule-reapply"])
    assert "Same job" not in result.output
    assert isinstance(result.exception, AssertionError)  # reached the booby-trapped client
    with store.open_store(config.db_path) as conn:
        assert store.get_reapply_decision(conn, jd_id).decision == "overrule"


def test_possibly_same_asks_then_jd_same_decides(config):
    add_outside(config, 90, req="JR_000123")  # number only on the earlier application
    jd_id = add_ad(config)
    result = runner.invoke(app, ["score", str(jd_id)])
    assert result.exit_code == 2
    text = flat(result)
    assert "Possibly the same job" in text and f"jobagent jd same {jd_id} yes" in text
    assert "requisition JR_000123 on the earlier one, none in this ad" in text

    assert runner.invoke(app, ["jd", "same", str(jd_id), "yes"]).exit_code == 0
    assert "Same job you applied for" in flat(runner.invoke(app, ["score", str(jd_id)]))

    assert runner.invoke(app, ["jd", "same", str(jd_id), "no"]).exit_code == 0
    cleared = runner.invoke(app, ["score", str(jd_id)])
    assert "Same job" not in cleared.output and "Possibly" not in cleared.output


def test_generate_is_refused_too(config):
    add_outside(config, 30, req="JR_000123")
    jd_id = add_ad(config, req="JR_000123")
    result = runner.invoke(app, ["generate", str(jd_id), "--resume"])
    assert result.exit_code == 2 and f"jobagent generate {jd_id} --overrule-reapply" in flat(result)


def test_outside_the_window_nothing_is_said(config):
    add_outside(config, 200, req="JR_000123")
    jd_id = add_ad(config, req="JR_000123")
    result = runner.invoke(app, ["score", str(jd_id)])
    assert "Same job" not in result.output and "Possibly" not in result.output


def test_jd_same_rejects_other_answers(config):
    jd_id = add_ad(config)
    assert runner.invoke(app, ["jd", "same", str(jd_id), "maybe"]).exit_code == 2
