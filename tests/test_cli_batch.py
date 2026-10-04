"""`jobagent batch` and `jobagent score ID ID …`. No network; invented ads."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from jobagent.adapters.adtext import ExtractedAd
from jobagent.cli import batch as batch_cli
from jobagent.cli import score as score_cli
from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import (
    ApplicationStatus,
    FitAssessment,
    JobDescription,
    Verdict,
    WorkArrangement,
    WorkType,
)
from jobagent.services import ads, scoring
from tests.ui_seed import jd as seed_jd

runner = CliRunner()
EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
AD = "Engineering Manager at {co}. An invented advertisement. " * 40


def flat(result) -> str:
    return " ".join(result.output.split())


@pytest.fixture
def config(tmp_path, monkeypatch):
    jds = tmp_path / "jds"
    jds.mkdir()
    cfg = Config(_env_file=None, db_path=tmp_path / "db", jd_dir=jds, output_dir=tmp_path / "out",
                 profile_dir=EXAMPLE_PROFILE, llm_default="anthropic:claude-sonnet-5")
    for module in (batch_cli, score_cli):
        monkeypatch.setattr(module, "get_config", lambda: cfg)
    with store.open_store(cfg.db_path) as conn:
        old = seed_jd("Old role", "Contoso Health", 0)
        old.ingested_at = datetime.now(timezone.utc) - timedelta(hours=2)
        store.add_jd(conn, old)

    def parse_jd(text, *, client, source):
        company = text.split(" at ")[1].split(".")[0]
        return JobDescription(title="Engineering Manager", company=company,
                              work_type=WorkType.permanent, work_arrangement=WorkArrangement.hybrid,
                              raw_text=text, ingested_at=datetime.now(timezone.utc))

    monkeypatch.setattr(ads, "parse_jd", parse_jd)
    monkeypatch.setattr(batch_cli, "get_client", lambda call_type, cfg_, ctx: SimpleNamespace(context=ctx))

    real_extract = ads.extract_saved_page

    def extract(file):
        if file.suffix == ".pdf":
            return ExtractedAd(text="Half an ad", full_text="x" * 3000, source_url=None,
                               page_title=None, posting_metadata=None, truncated=True)
        return real_extract(file)

    monkeypatch.setattr(ads, "extract_saved_page", extract)
    return cfg


def save(cfg, name, text):
    path = cfg.jd_dir / name
    path.write_text(text)
    now = datetime.now().timestamp()
    os.utime(path, (now, now))


def test_batch_shows_new_files_and_cost_without_spending(config):
    save(config, "acme.txt", AD.format(co="Acme Logistics"))
    result = runner.invoke(app, ["batch"])
    assert result.exit_code == 0, result.output
    assert "1 new saved ad(s)" in result.output and "acme.txt" in result.output
    assert "jobagent batch parse" in flat(result)
    with store.open_store(config.db_path) as conn:
        assert len(store.list_jds(conn)) == 1  # nothing parsed


def test_batch_parse_table_includes_the_refused_row(config):
    save(config, "acme.txt", AD.format(co="Acme Logistics"))
    save(config, "cutoff.pdf", "%PDF stand-in")
    result = runner.invoke(app, ["batch", "parse"])
    assert result.exit_code == 0, result.output
    text = flat(result)
    assert "Acme Logistics" in text
    assert "cutoff.pdf" in text and "Cut off at '…more'" in text and "refused" in text
    assert "Nothing new" in flat(runner.invoke(app, ["batch", "parse"]))


def test_batch_skip_records_not_applied(config):
    with store.open_store(config.db_path) as conn:
        jd_id = store.add_jd(conn, seed_jd("Engineering Manager", "Fabrikam Medical", 5))
    result = runner.invoke(app, ["batch", "skip", str(jd_id), "999"])
    assert f"JD {jd_id}" in result.output and "No job description with id 999" in result.output
    with store.open_store(config.db_path) as conn:
        assert store.get_application(conn, jd_id).status is ApplicationStatus.not_applied


def test_score_several_with_one_refused(config, monkeypatch):
    with store.open_store(config.db_path) as conn:
        good = store.add_jd(conn, seed_jd("Engineering Manager", "Acme Logistics", 5))
        stub = seed_jd("Digital Lead", "Contoso Health", 5)
        stub.raw_text = "Two sentences only. Apply now."
        thin = store.add_jd(conn, stub)

    scored = []
    monkeypatch.setattr(score_cli, "get_client", lambda *a, **k: object())
    monkeypatch.setattr(scoring, "score_fit", lambda jd_, profile, *, client: scored.append(jd_.id) or FitAssessment(
        jd_id=jd_.id, overall_score=70, recruiter_screen_score=60, verdict=Verdict.apply,
        rationale="Invented.", target_role_match=True, target_role_note="Invented.",
        scored_at=datetime.now(timezone.utc)))
    result = runner.invoke(app, ["score", str(good), str(thin)])
    assert result.exit_code == 0, result.output
    text = flat(result)
    assert scored == [good]
    assert f"Scored 1: {good}" in text and f"Refused 1: {thin}" in text
    assert "too little to score" in text


def test_last_and_json_take_one_id(config):
    assert runner.invoke(app, ["score", "1", "2", "--last"]).exit_code == 2
