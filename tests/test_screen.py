"""The cheap first-pass screen: what it is shown, what it stores, when it reuses."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from jobagent.config import Config
from jobagent.core import store
from jobagent.core.profile import load_profile
from jobagent.core.screen import candidate_summary, screen
from jobagent.services import screening
from jobagent.services.workspace import Workspace
from tests.quality_seed import RoutedClient, northwind
from tests.ui_seed import seed, workspace

EXAMPLE = Path(__file__).resolve().parents[1] / "profile.example"
CONFIG = Config(_env_file=None, llm_default="anthropic:claude-sonnet-5")


@pytest.fixture
def profile():
    return load_profile(EXAMPLE)


def test_the_screen_sees_the_parsed_ad_and_a_summary_never_a_scorer_note(profile):
    client = RoutedClient({"screen_fit": {"decision": "skip", "reason": "An SRE role."}})
    result = screen(northwind(), profile, client=client)
    assert (result.decision, result.reason) == ("skip", "An SRE role.")
    prompt = client.prompts["screen_fit"][0]
    assert "Coaching and growing engineers" in prompt and "Targets: Engineering Manager" in prompt
    assert "route planning" not in prompt  # the raw text stays out
    notes = [s.note_for_scorer for s in profile.stories.stories if s.note_for_scorer]
    assert notes and not any(n.split(".")[0] in prompt for n in notes)


def test_an_answer_that_is_neither_goes_through_to_scoring(profile):
    client = RoutedClient({"screen_fit": {"decision": "maybe", "reason": "Unsure."}})
    assert screen(northwind(), profile, client=client).decision == "score"


def test_the_service_stores_reuses_and_forces(tmp_path):
    ws = Workspace(**{**workspace(tmp_path).__dict__, "profile_dir": EXAMPLE})
    ids = seed(ws)
    client = RoutedClient({"screen_fit": [
        {"decision": "skip", "reason": "Wrong level."},
        {"decision": "score", "reason": "Worth a look."},
    ]})
    first = screening.screen_ads(ws, CONFIG, [ids["acme"], 999], client_factory=lambda ctx: client)
    assert [(r.decision, r.reused) for r in first] == [("skip", False), (None, False)]
    again = screening.screen_ads(ws, CONFIG, [ids["acme"]], client_factory=lambda ctx: client)
    assert again[0].reused and again[0].decision == "skip"
    forced = screening.screen_ads(ws, CONFIG, [ids["acme"]], force=True, client_factory=lambda ctx: client)
    assert forced[0].decision == "score"
    with store.open_store(ws.db_path) as conn:
        assert store.get_screen(conn, ids["acme"])["decision"] == "score"
        jd = store.get_jd(conn, ids["acme"])
        store.update_jd(conn, ids["acme"], jd, amended_at=datetime.now(timezone.utc))
        assert store.get_screen(conn, ids["acme"]) is None  # a changed ad is screened afresh
