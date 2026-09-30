"""Local-only access: the Host check and the POST token. No network."""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from jobagent.config import Config
from jobagent.services.workspace import Workspace
from jobagent.web.app import CSRF_COOKIE, checked_form, create_app

PORT = 8765
TOKEN = "test-token"


@pytest.fixture
def app(tmp_path):
    config = Config(_env_file=None, db_path=tmp_path / "db", output_dir=tmp_path / "out")
    app = create_app(
        workspace_factory=lambda: Workspace.from_config(config),
        config=config,
        port=PORT,
        token=TOKEN,
    )

    @app.post("/_probe")
    async def probe(request: Request):
        await checked_form(request)
        return {"ok": True}

    return app


def client(app, host=f"127.0.0.1:{PORT}") -> TestClient:
    return TestClient(app, base_url=f"http://{host}", follow_redirects=False)


def test_wrong_host_is_refused(app):
    response = client(app, host="evil.example:8765").get("/static/README.md")
    assert response.status_code == 403


def test_right_host_is_served(app):
    assert client(app).get("/static/README.md").status_code == 200
    assert client(app, host=f"localhost:{PORT}").get("/static/README.md").status_code == 200


def test_token_link_sets_cookie_and_drops_token_from_url(app):
    response = client(app).get(f"/?t={TOKEN}")
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert f"{CSRF_COOKIE}={TOKEN}" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie


def test_wrong_token_link_is_refused(app):
    assert client(app).get("/?t=guess").status_code == 403


def test_post_without_token_is_refused(app):
    assert client(app).post("/_probe", data={}).status_code == 403


def test_post_with_mismatched_token_is_refused(app):
    c = client(app)
    c.cookies.set(CSRF_COOKIE, TOKEN)
    assert c.post("/_probe", data={"csrf": "other"}).status_code == 403


def test_post_with_field_but_no_cookie_is_refused(app):
    assert client(app).post("/_probe", data={"csrf": TOKEN}).status_code == 403


def test_post_with_token_and_cookie_is_accepted(app):
    c = client(app)
    c.get(f"/?t={TOKEN}")
    response = c.post("/_probe", data={"csrf": TOKEN})
    assert response.status_code == 200
