"""`jobagent ui` — start the local UI and open it in the browser.

Foreground, on purpose: Ctrl-C stops it, and there is no daemon, PID file or
stop command to forget about (research R10). It listens on 127.0.0.1 only and
there is no option to change that.
"""

from __future__ import annotations

import secrets
import socket
import threading
import time
import webbrowser

import typer
import uvicorn
from rich.console import Console

from jobagent.config import get_config
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app

console = Console()
err_console = Console(stderr=True)

HOST = "127.0.0.1"


def ui(
    port: int = typer.Option(8765, "--port", help="Port to listen on, on 127.0.0.1."),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Print the link instead of opening it."
    ),
) -> None:
    """Start the local UI on this machine and open it in the browser."""
    config = get_config()
    if _port_busy(port):
        err_console.print(
            f"[bold red]Something is already listening on http://{HOST}:{port}[/] "
            "— probably another `jobagent ui`. Use that one, or pass --port."
        )
        raise typer.Exit(code=2)

    token = secrets.token_urlsafe(24)
    app = create_app(
        workspace_factory=lambda: Workspace.from_config(get_config()),
        config=config,
        port=port,
        token=token,
    )
    url = f"http://{HOST}:{port}/?t={token}"
    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    )

    console.print(f"Local UI on [bold]http://{HOST}:{port}[/] — Ctrl-C to stop.")
    if config.budget_mode:
        console.print("[yellow]Budget mode: model calls go to the free tier.[/]")
    if no_browser:
        console.print(f"Open: {url}")
    else:
        threading.Thread(
            target=_open_when_listening, args=(server, url), daemon=True
        ).start()
    _serve(server)


def _serve(server: uvicorn.Server) -> None:
    server.run()


def _open_when_listening(server: uvicorn.Server, url: str, timeout: float = 10.0) -> None:
    """Open the browser once the socket is up, so the first page load succeeds."""
    deadline = time.monotonic() + timeout
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if server.started:
        _open_browser(url)
    else:
        err_console.print(f"[yellow]The server did not start in time. Open {url} yourself.[/]")


def _open_browser(url: str) -> None:
    webbrowser.open(url)


def _port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return True
    return False
