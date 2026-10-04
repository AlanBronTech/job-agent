"""services.batches: one row per file, refusals as rows, resume, baseline. Invented data."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobagent.adapters.adtext import ExtractedAd
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import JobDescription, WorkArrangement, WorkType
from jobagent.services import ads, batches
from jobagent.services.workspace import Workspace
from tests.ui_seed import jd as seed_jd
from tests.ui_seed import workspace

EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
CONFIG = Config(_env_file=None, llm_default="anthropic:claude-sonnet-5")
TODAY = date.today()
AD = "Engineering Manager at {co}. An invented advertisement. " * 40


@pytest.fixture
def ws(tmp_path):
    base = workspace(tmp_path)
    ws = Workspace(**{**base.__dict__, "profile_dir": EXAMPLE_PROFILE})
    ws.jd_dir.mkdir()
    with store.open_store(ws.db_path) as conn:  # the latest ad added: two hours ago
        old = seed_jd("Old role", "Contoso Health", 0)
        old.ingested_at = datetime.now(timezone.utc) - timedelta(hours=2)
        store.add_jd(conn, old)
    return ws


@pytest.fixture
def parser(monkeypatch):
    """A fake parse that records calls; the company is read off the text."""
    calls = []

    def parse_jd(text, *, client, source):
        calls.append(text)
        company = text.split(" at ")[1].split(".")[0]
        return JobDescription(title="Engineering Manager", company=company,
                              work_type=WorkType.permanent, work_arrangement=WorkArrangement.hybrid,
                              raw_text=text, ingested_at=datetime.now(timezone.utc))

    monkeypatch.setattr(ads, "parse_jd", parse_jd)
    monkeypatch.setattr(ads, "get_client", lambda call_type, config, ctx: SimpleNamespace(context=ctx))
    return calls


def save(ws, name, text, minutes_ago=0):
    path = ws.jd_dir / name
    path.write_text(text)
    stamp = (datetime.now() - timedelta(minutes=minutes_ago)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_old_files_are_not_offered(ws):
    save(ws, "old.txt", AD.format(co="Northwind Freight"), minutes_ago=600)
    assert batches.new_files(ws) == []
    assert batches.start(ws) is None


def test_one_row_per_file_including_refusals(ws, parser, monkeypatch):
    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    save(ws, "fabrikam.txt", AD.format(co="Fabrikam Medical") + " Requisition: JR_000123.")
    save(ws, "cutoff.pdf", "%PDF stand-in")
    with store.open_store(ws.db_path) as conn:
        stored = store.add_jd(conn, seed_jd("Platform Lead", "Northwind Freight", 1))
        stored_text = store.get_jd(conn, stored).raw_text
    save(ws, "again.txt", stored_text)

    real_extract = ads.extract_saved_page

    def extract(file):
        if file.name == "cutoff.pdf":
            return ExtractedAd(text="Half an ad", full_text="x" * 3000, source_url=None,
                               page_title=None, posting_metadata=None, truncated=True)
        return real_extract(file)

    monkeypatch.setattr(ads, "extract_saved_page", extract)

    batch = batches.start(ws)
    spent = []
    batches.parse(ws, CONFIG, batch, before_spend=lambda: spent.append(True))
    table = {r.file_name: r for r in batches.rows(ws, batch, TODAY)}

    assert set(table) == {"acme.txt", "fabrikam.txt", "cutoff.pdf", "again.txt"}  # SC-003
    assert table["cutoff.pdf"].refusal == batches.TRUNCATED
    assert "Cut off at '…more'" in batches.describe(table["cutoff.pdf"].refusal, None)
    assert table["again.txt"].refusal == batches.DUPLICATE
    assert table["again.txt"].refusal_detail == str(stored)
    assert table["acme.txt"].state == "parsed" and table["acme.txt"].company == "Acme Logistics"
    assert table["fabrikam.txt"].requisition_id == "JR_000123"
    assert table["acme.txt"].filters  # free hard filters computed
    assert len(parser) == 2 and spent == [True]


def test_parsed_files_are_not_offered_again(ws, parser):
    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    batch = batches.start(ws)
    batches.parse(ws, CONFIG, batch)
    assert batches.new_files(ws) == []


def test_resume_repeats_no_paid_step(ws, parser, monkeypatch):
    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    save(ws, "fabrikam.txt", AD.format(co="Fabrikam Medical"))
    batch = batches.start(ws)

    real = ads.add
    state = {"n": 0}

    def flaky(*a, **k):
        state["n"] += 1
        if state["n"] == 2:
            raise KeyboardInterrupt  # the batch stops part-way
        return real(*a, **k)

    monkeypatch.setattr(ads, "add", flaky)
    with pytest.raises(KeyboardInterrupt):
        batches.parse(ws, CONFIG, batch)
    assert len(parser) == 1 and batches.waiting(ws, batch) == ["fabrikam.txt"]

    monkeypatch.setattr(ads, "add", real)
    batches.parse(ws, CONFIG, batch)
    assert len(parser) == 2 and batches.waiting(ws, batch) == []


def test_a_refused_file_is_offered_again_once_saved_again(ws, parser, monkeypatch):
    save(ws, "cutoff.pdf", "%PDF stand-in")
    monkeypatch.setattr(ads, "extract_saved_page", lambda file: ExtractedAd(
        text="Half", full_text="x" * 3000, source_url=None, page_title=None,
        posting_metadata=None, truncated=True))
    batch = batches.start(ws, now=datetime.now(timezone.utc))
    batches.parse(ws, CONFIG, batch)
    assert batches.new_files(ws) == []  # not re-offered until saved again
    future = (datetime.now() + timedelta(minutes=5)).timestamp()
    os.utime(ws.jd_dir / "cutoff.pdf", (future, future))
    assert [p.name for p in batches.new_files(ws)] == ["cutoff.pdf"]


def test_two_files_with_one_requisition_are_both_flagged(ws, parser):
    save(ws, "a.txt", AD.format(co="Fabrikam Medical") + " Requisition: JR_000123.", minutes_ago=1)
    save(ws, "b.txt", AD.format(co="Fabrikam Medical") + " Reference: JR-000123. Apply now.")
    batch = batches.start(ws)
    batches.parse(ws, CONFIG, batch)
    table = batches.rows(ws, batch, TODAY)
    assert [r.same_requisition_as for r in table] == [None, 1]
    assert table[0].requisition_id and table[1].requisition_id


def test_a_failed_parse_is_a_row_not_a_crash(ws, parser, monkeypatch):
    from jobagent.core.jd import JDError

    save(ws, "acme.txt", AD.format(co="Acme Logistics"))

    def broken(text, *, client, source):
        raise JDError("the model returned nonsense")

    monkeypatch.setattr(ads, "parse_jd", broken)
    batch = batches.start(ws)
    batches.parse(ws, CONFIG, batch)
    row = batches.rows(ws, batch, TODAY)[0]
    assert row.refusal == batches.PARSE_FAILED and "nonsense" in row.refusal_detail


def test_a_failed_parse_is_retried_on_the_next_parse(ws, parser, monkeypatch):
    from jobagent.core.jd import JDError

    save(ws, "acme.txt", AD.format(co="Acme Logistics"))
    real = ads.parse_jd

    def once_broken(text, *, client, source):
        monkeypatch.setattr(ads, "parse_jd", real)
        raise JDError("timed out")

    monkeypatch.setattr(ads, "parse_jd", once_broken)
    batch = batches.start(ws)
    batches.parse(ws, CONFIG, batch)
    assert batches.waiting(ws, batch) == ["acme.txt"]
    batches.parse(ws, CONFIG, batch)
    row = batches.rows(ws, batch, TODAY)[0]
    assert row.refusal is None and row.state == "parsed"
