"""The Settings page: choices saved beside the database, applied everywhere."""

from __future__ import annotations

from fastapi.testclient import TestClient

from jobagent.adapters.llm import CallType, resolve_effort, resolve_route
from jobagent.config import Config
from jobagent.services import settings
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from jobagent.web.runner import SyncRunner
from tests.ui_seed import workspace


def config(tmp_path, **extra):
    return Config(_env_file=None, db_path=tmp_path / "jobagent.db", llm_default="anthropic:claude-sonnet-5",
                  anthropic_api_key="a", gemini_api_key="g", **extra)


def test_saved_settings_override_env_and_defaults(tmp_path):
    cfg = config(tmp_path, review=False)
    settings.save(cfg, {"routes": {"score": "anthropic:claude-haiku-4-5-20251001"},
                        "efforts": {"generate": "high"}, "check_claims": False, "review": True})
    applied = settings.apply(cfg)
    assert resolve_route(applied, CallType.score).model == "claude-haiku-4-5-20251001"
    assert resolve_effort(applied, CallType.generate) == "high"
    assert resolve_effort(applied, CallType.parse_jd) == "low"  # untouched default
    assert (applied.check_claims, applied.review) == (False, True)


def test_no_file_changes_nothing_and_a_bad_file_is_ignored(tmp_path):
    cfg = config(tmp_path)
    assert settings.apply(cfg) is cfg
    settings.path_for(cfg).write_text("{not json", encoding="utf-8")
    assert settings.apply(cfg) is cfg


def test_the_page_saves_and_shows_what_was_chosen(tmp_path):
    cfg = config(tmp_path)
    app = create_app(workspace_factory=lambda: workspace(tmp_path), config=cfg, port=8765,
                     token="t", runner=SyncRunner())
    client = TestClient(app, base_url="http://127.0.0.1:8765", follow_redirects=False)
    client.get("/?t=t")
    page = client.get("/settings").text
    assert "Read an ad" in page and "Default (gemini-2.5-flash)" in page
    assert "Default (claude-haiku-4-5-20251001)" in page  # the screen
    saved = client.post("/settings", data={
        "csrf": "t", "route_score": "anthropic:claude-haiku-4-5-20251001",
        "route_parse_jd": "made-up:model", "effort_score": "low", "review": "1"})
    assert saved.status_code == 303
    data = settings.load(cfg)
    assert data["routes"] == {"score": "anthropic:claude-haiku-4-5-20251001"}  # the made-up route is dropped
    assert data["efforts"] == {"score": "low"} and data["review"] is True and data["check_claims"] is False
    assert 'value="anthropic:claude-haiku-4-5-20251001" selected' in client.get("/settings?saved=1").text


def test_a_post_without_the_token_is_refused(tmp_path):
    cfg = config(tmp_path)
    app = create_app(workspace_factory=lambda: workspace(tmp_path), config=cfg, port=8765,
                     token="t", runner=SyncRunner())
    client = TestClient(app, base_url="http://127.0.0.1:8765", follow_redirects=False)
    client.get("/?t=t")
    assert client.post("/settings", data={"csrf": "wrong"}).status_code in (400, 403)
    assert settings.load(cfg) == {}
