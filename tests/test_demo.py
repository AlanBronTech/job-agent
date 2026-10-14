"""`jobagent ui --demo`: an invented workspace, seeded without spending."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from jobagent import demo
from jobagent.config import Config
from jobagent.core import store
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from jobagent.web.runner import SyncRunner


def test_the_demo_seeds_once_and_every_page_renders(tmp_path):
    assert demo.ensure(tmp_path, today=date(2026, 10, 14)) is True
    assert demo.ensure(tmp_path) is False  # never reseeded over a demo in progress
    paths = demo.paths(tmp_path)
    with store.open_store(paths["db_path"]) as conn:
        assert len(store.list_jds(conn)) == 7
    folder = next(paths["output_dir"].iterdir())
    assert {p.suffix for p in folder.iterdir()} >= {".docx", ".md"}
    assert not paths["runs_log_path"].exists()  # nothing was spent

    cfg = Config(_env_file=None, **paths)
    app = create_app(workspace_factory=lambda: Workspace.from_config(cfg), config=cfg,
                     port=8765, token="t", runner=SyncRunner())
    client = TestClient(app, base_url="http://127.0.0.1:8765", follow_redirects=False)
    client.get("/?t=t")
    for url in ["/", "/?sort=score", "/ads/1", "/ads/4", "/ads/7", "/batch", "/ads/new", "/settings"]:
        assert client.get(url).status_code == 200, url
    assert "Northwind Freight" in client.get("/").text
