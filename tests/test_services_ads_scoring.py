"""services.ads and services.scoring: refusals before spend, what gets stored."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobagent.adapters.adtext import ExtractedAd
from jobagent.adapters.llm import LLMError, RunContext
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import FitAssessment, JobDescription, Verdict, WorkArrangement, WorkType
from jobagent.services import ads, scoring
from jobagent.services.refusals import (
    CaptureTruncated,
    NoModel,
    NoSuchAd,
    ProfileMissing,
    ThinAd,
    UnreadableAd,
)
from jobagent.services.workspace import Workspace
from tests.ui_seed import jd as make_jd
from tests.ui_seed import seed, workspace

EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
CONFIG = Config(_env_file=None, llm_default="anthropic:claude-sonnet-5")
AD = "Engineering Manager at Acme Logistics. An invented advertisement. " * 30


@pytest.fixture
def ws(tmp_path):
    base = workspace(tmp_path)
    return Workspace(**{**base.__dict__, "profile_dir": EXAMPLE_PROFILE})


def no_client(*a, **k):
    raise AssertionError("a client was built before every refusal had passed")


def fake_client(ctx):
    return SimpleNamespace(context=ctx)


# -- reading an ad: free -------------------------------------------------------


def test_read_plain_text_file(tmp_path):
    path = tmp_path / "acme.txt"
    path.write_text(AD)
    ad = ads.read_ad(file=path)
    assert ad.raw_text == AD and ad.name == "acme.txt"
    assert ad.page_chars is None and ad.thin_chars is None


def test_read_pasted_text():
    ad = ads.read_ad(text="Short pasted ad.")
    assert ad.raw_text == "Short pasted ad." and ad.thin_chars is None  # only saved pages warn


def test_read_a_saved_page_reports_size_and_thinness(tmp_path, monkeypatch):
    page = ExtractedAd(text="Collapsed.", full_text="x" * 5000, source_url="https://example.invalid/1",
                       page_title=None, posting_metadata="Posted 3 days ago", truncated=False)
    monkeypatch.setattr(ads, "extract_saved_page", lambda file: page)
    ad = ads.read_ad(file=tmp_path / "acme.pdf")
    assert ad.page_chars == 5000 and ad.thin_chars == len("Collapsed.")
    assert ad.source_url == "https://example.invalid/1" and ad.posting_metadata == "Posted 3 days ago"


def test_unreadable_file(tmp_path):
    with pytest.raises(UnreadableAd):
        ads.read_ad(file=tmp_path / "missing.txt")


def test_exactly_one_input():
    with pytest.raises(ValueError):
        ads.read_ad()


# -- adding an ad: paid ---------------------------------------------------------


def test_a_truncated_capture_is_refused_before_a_client(ws, monkeypatch):
    monkeypatch.setattr(ads, "get_client", no_client)
    with pytest.raises(CaptureTruncated):
        ads.add(ws, CONFIG, RunContext(command="jd add", source="ui"),
                ads.AdInput(raw_text="Half an ad", page_chars=900, truncated=True))


def test_no_model(ws, monkeypatch):
    def unroutable(*a, **k):
        raise LLMError("no route")
    monkeypatch.setattr(ads, "get_client", unroutable)
    with pytest.raises(NoModel):
        ads.add(ws, CONFIG, RunContext(command="jd add"), ads.AdInput(raw_text=AD))


def test_add_stores_attributes_and_reports_history(ws, monkeypatch):
    seed(ws)  # includes two Northwind Freight ads
    ctx = RunContext(command="jd add", source="ui")
    spent = []
    monkeypatch.setattr(ads, "get_client", lambda call_type, config, context: fake_client(context))

    def parse(text, *, client, source):
        spent.append(text)
        return make_jd("Platform Engineer", "Northwind Freight", 20)
    monkeypatch.setattr(ads, "parse_jd", parse)

    result = ads.add(ws, CONFIG, ctx, ads.AdInput(raw_text=AD, source_url="https://example.invalid/2"),
                     source="seek", before_spend=lambda: spent.append("estimate"))

    assert spent == ["estimate", AD]
    with store.open_store(ws.db_path) as conn:
        stored = store.get_jd(conn, result.jd.id)
    assert stored.source_url == "https://example.invalid/2"
    assert len(result.history.encounters) == 2
    records = [json.loads(line) for line in ws.runs_log_path.read_text().splitlines()]
    assert records == [{**records[0], "type": "attribution", "run_id": ctx.run_id, "jd_id": result.jd.id}]


# -- scoring: paid --------------------------------------------------------------


@pytest.fixture
def stub_id(ws):
    with store.open_store(ws.db_path) as conn:
        return store.add_jd(conn, JobDescription(
            title="Engineering Manager", company="Acme Logistics",
            work_type=WorkType.permanent, work_arrangement=WorkArrangement.hybrid,
            raw_text="Two sentences only. Apply now.", ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc)))


def test_missing_ad(ws):
    with pytest.raises(NoSuchAd):
        scoring.score(ws, CONFIG, RunContext(command="score"), 999, client_factory=no_client)


def test_a_stub_is_refused_before_a_client(ws, stub_id):
    with pytest.raises(ThinAd) as refused:
        scoring.score(ws, CONFIG, RunContext(command="score"), stub_id, client_factory=no_client)
    assert refused.value.chars == len("Two sentences only. Apply now.")


def test_force_gets_past_the_stub_check_to_the_next_gate(ws, stub_id):
    no_profile = Workspace(**{**ws.__dict__, "profile_dir": None})
    with pytest.raises(ProfileMissing):
        scoring.score(no_profile, CONFIG, RunContext(command="score"), stub_id,
                      force=True, client_factory=no_client)


def test_score_stores_the_assessment(ws, monkeypatch):
    ids = seed(ws)
    order = []

    def fake_score(jd, profile, *, client):
        order.append("model")
        return FitAssessment(jd_id=jd.id, overall_score=66, recruiter_screen_score=60,
                             verdict=Verdict.apply, rationale="Invented.", target_role_match=True,
                             target_role_note="Invented.", scored_at=datetime.now(timezone.utc))
    monkeypatch.setattr(scoring, "score_fit", fake_score)

    result = scoring.score(ws, CONFIG, RunContext(command="score", source="ui"), ids["contoso"],
                           client_factory=lambda: object(), before_spend=lambda: order.append("estimate"))

    assert order == ["estimate", "model"]
    assert result.assessment.id is not None and result.warnings == []
    with store.open_store(ws.db_path) as conn:
        assert store.latest_assessment(conn, ids["contoso"]).overall_score == 66


def test_a_failed_save_is_a_warning(ws, monkeypatch):
    ids = seed(ws)
    monkeypatch.setattr(scoring, "score_fit", lambda jd, profile, *, client: FitAssessment(
        jd_id=jd.id, overall_score=50, recruiter_screen_score=50, verdict=Verdict.skip,
        rationale="Invented.", target_role_match=False, target_role_note="Invented.",
        scored_at=datetime.now(timezone.utc)))

    def broken(conn, assessment):
        raise store.StoreError("disk full")
    monkeypatch.setattr(scoring.store, "add_assessment", broken)
    result = scoring.score(ws, CONFIG, RunContext(command="score"), ids["contoso"],
                           client_factory=lambda: object())
    assert result.warnings == ["Scored, but could not save. disk full"]


def test_add_records_the_source_file_and_requisition_number(ws, monkeypatch):
    ctx = RunContext(command="jd add", source="cli")
    monkeypatch.setattr(ads, "get_client", lambda call_type, config, context: fake_client(context))
    monkeypatch.setattr(ads, "parse_jd", lambda text, *, client, source: make_jd("Engineering Manager", "Fabrikam Medical", 1))
    text = AD + " Requisition: JR_000123."
    filed = ads.add(ws, CONFIG, ctx, ads.AdInput(raw_text=text, name="fabrikam-em.pdf"))
    pasted = ads.add(ws, CONFIG, RunContext(command="jd add"), ads.AdInput(raw_text=AD))
    with store.open_store(ws.db_path) as conn:
        a, b = store.get_jd(conn, filed.jd.id), store.get_jd(conn, pasted.jd.id)
    assert (a.source_file, a.requisition_id) == ("fabrikam-em.pdf", "JR_000123")
    assert (b.source_file, b.requisition_id) == (None, None)


# -- backfill (spec 002, US4) ----------------------------------------------------


def test_backfill_sets_exactly_and_reports_ambiguity(ws, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("backfill built a model client")

    monkeypatch.setattr(ads, "get_client", refuse)
    ws.jd_dir.mkdir()
    with store.open_store(ws.db_path) as conn:
        one = make_jd("Engineering Manager", "Fabrikam Medical", 1)
        one.raw_text = AD + " Requisition: JR_000123."
        one_id = store.add_jd(conn, one)
        two = make_jd("Engineering Manager", "Northwind Freight", 2)
        two.raw_text = AD + " Ref: JR_000456. See also JR_000789."
        two_id = store.add_jd(conn, two)
        plain_id = store.add_jd(conn, make_jd("Head of Engineering", "Contoso Health", 3))
        plain_text = store.get_jd(conn, plain_id).raw_text
    (ws.jd_dir / "fabrikam.txt").write_text(one.raw_text)
    (ws.jd_dir / "contoso-a.txt").write_text(plain_text)
    (ws.jd_dir / "contoso-b.txt").write_text(plain_text)

    report = ads.backfill(ws)

    assert report.requisitions_set == [(one_id, "JR_000123")]
    assert report.requisitions_ambiguous == [(two_id, ["JR_000456", "JR_000789"])]
    assert report.files_set == [(one_id, "fabrikam.txt")]
    assert report.files_ambiguous == [(plain_id, ["contoso-a.txt", "contoso-b.txt"])] or \
        report.files_ambiguous == [(plain_id, ["contoso-b.txt", "contoso-a.txt"])]
    with store.open_store(ws.db_path) as conn:
        got = store.get_jd(conn, one_id)
        assert (got.requisition_id, got.source_file) == ("JR_000123", "fabrikam.txt")
        assert store.get_jd(conn, two_id).requisition_id is None
    assert ads.backfill(ws).requisitions_set == []  # idempotent
