"""services.role_kind: classify once, store, free thereafter; amend reclassifies."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jobagent.adapters.llm import RunContext
from jobagent.config import Config
from jobagent.core import store
from jobagent.services import role_kind
from tests.quality_seed import RoutedClient
from tests.ui_seed import seed, workspace

CONFIG = Config(_env_file=None, llm_default="anthropic:claude-sonnet-5")
CTX = RunContext(command="score")


def answer(primary="people_focused"):
    return RoutedClient({"classify_role": {"primary": primary, "secondary": None, "reason": "Invented."}})


def test_classified_once_then_free(tmp_path):
    ws = workspace(tmp_path)
    ids = seed(ws)
    assert role_kind.needs_classify(ws, ids["acme"])
    client = answer()
    kind = role_kind.ensure(ws, CONFIG, CTX, ids["acme"], client_factory=lambda: client)
    assert kind.primary.value == "people_focused"
    assert not role_kind.needs_classify(ws, ids["acme"])

    def refuse():
        raise AssertionError("a stored kind must not be paid for twice")
    assert role_kind.ensure(ws, CONFIG, CTX, ids["acme"], client_factory=refuse) == kind


def test_an_amendment_means_classifying_again(tmp_path):
    ws = workspace(tmp_path)
    ids = seed(ws)
    role_kind.ensure(ws, CONFIG, CTX, ids["acme"], client_factory=answer)
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, ids["acme"])
        store.update_jd(conn, ids["acme"], jd, amended_at=datetime(2026, 10, 7, tzinfo=timezone.utc))
    assert role_kind.needs_classify(ws, ids["acme"])


def test_an_unusable_answer_stores_nothing(tmp_path):
    ws = workspace(tmp_path)
    ids = seed(ws)
    bad = RoutedClient({"classify_role": {"primary": "chef", "reason": "x"}})
    with pytest.raises(role_kind.RoleKindFailed):
        role_kind.ensure(ws, CONFIG, CTX, ids["acme"], client_factory=lambda: bad)
    assert role_kind.stored(ws, ids["acme"]) is None
