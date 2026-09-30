"""`jobagent ui`: bind address, token link, busy port. Server and browser faked."""

from __future__ import annotations

import socket

import pytest
from typer.testing import CliRunner

from jobagent.cli import ui as ui_cli
from jobagent.cli.main import app
from jobagent.config import Config

runner = CliRunner()


@pytest.fixture
def served(tmp_path, monkeypatch):
    config = Config(_env_file=None, db_path=tmp_path / "db", output_dir=tmp_path / "out")
    monkeypatch.setattr(ui_cli, "get_config", lambda: config)
    captured = {}

    def fake_serve(server):
        captured["server"] = server
        server.started = True
        # Run the opener inline rather than on a thread, if one was started.
        if captured.get("url"):
            ui_cli._open_when_listening(server, captured["url"], timeout=0)

    opened = []
    monkeypatch.setattr(ui_cli, "_serve", fake_serve)
    monkeypatch.setattr(ui_cli, "_open_browser", opened.append)
    real_thread = ui_cli.threading.Thread

    class InlineThread:
        def __init__(self, target, args, daemon):
            captured["url"] = args[1]

        def start(self):
            pass

    monkeypatch.setattr(ui_cli.threading, "Thread", InlineThread)
    yield captured, opened
    monkeypatch.setattr(ui_cli.threading, "Thread", real_thread)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_binds_localhost_and_opens_token_link(served):
    captured, opened = served
    port = free_port()
    result = runner.invoke(app, ["ui", "--port", str(port)])
    assert result.exit_code == 0, result.output
    assert captured["server"].config.host == "127.0.0.1"
    assert captured["server"].config.port == port
    assert len(opened) == 1
    assert opened[0].startswith(f"http://127.0.0.1:{port}/?t=")
    assert len(opened[0].split("?t=")[1]) >= 24


def test_no_browser_prints_the_link(served):
    captured, opened = served
    port = free_port()
    result = runner.invoke(app, ["ui", "--port", str(port), "--no-browser"])
    assert f"http://127.0.0.1:{port}/?t=" in result.output
    assert opened == []


def test_busy_port_exits_2(served):
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        result = runner.invoke(app, ["ui", "--port", str(port)])
    assert result.exit_code == 2
    assert "already listening" in result.output


def test_there_is_no_host_option():
    result = runner.invoke(app, ["ui", "--host", "0.0.0.0"])
    assert result.exit_code != 0
