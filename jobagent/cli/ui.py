"""`jobagent ui` — start the local UI and open it in the browser.

Foreground, on purpose: Ctrl-C stops it, and there is no daemon, PID file or
stop command to forget about (research R10). It listens on 127.0.0.1 only and
there is no option to change that.
"""

from __future__ import annotations

import os
import secrets
import socket
import threading
import time
import webbrowser

import typer
import uvicorn
from rich.console import Console

from jobagent.config import get_config
from jobagent.services import runs
from jobagent.services.workspace import Workspace
from jobagent.web.app import create_app
from jobagent.web.runner import Runner

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

    ws = Workspace.from_config(config)
    interrupted = runs.interrupt_running(ws)
    if interrupted:
        console.print(
            f"[yellow]{interrupted} run(s) were still going when the UI last stopped; "
            "they are marked interrupted.[/]"
        )

    token = secrets.token_urlsafe(24)
    runner = Runner()
    app = create_app(
        workspace_factory=lambda: Workspace.from_config(get_config()),
        config=config,
        port=port,
        token=token,
        runner=runner,
    )
    url = f"http://{HOST}:{port}/?t={token}"
    server = _Server(
        uvicorn.Config(app, host=HOST, port=port, log_level="warning"),
        runner=runner,
        ws=ws,
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
    try:
        _serve(server)
    finally:
        _finish_runs(runner, ws)


def _finish_runs(runner: Runner, ws: Workspace) -> None:
    """Let a run in progress finish, so its result and cost are recorded.

    Python would wait for the worker thread anyway; saying so turns a silent
    hang into a choice. Ctrl-C here abandons it: the process exits at once,
    and the next start marks the run interrupted.
    """
    active = _describe(runner.active(ws))
    if not active:
        runner.shutdown()
        return
    err_console.print(
        f"[yellow]Waiting for {active} to finish so its result and cost are "
        "recorded. Ctrl-C to abandon it.[/]"
    )
    try:
        runner.wait()
    except KeyboardInterrupt:
        err_console.print(
            "[yellow]Abandoned. It will show as interrupted next time, and its cost "
            "may be missing from `jobagent spend`.[/]"
        )
        _hard_exit(130)


def _hard_exit(code: int) -> None:
    os._exit(code)


def _describe(active) -> str:
    return ", ".join(f"{r.kind} (JD {r.jd_id})" if r.jd_id else r.kind for r in active)


class _Server(uvicorn.Server):
    """Asks for a second Ctrl-C while a run is going.

    Stopping the server ends a run the way killing a command does: whatever
    the model has generated is billed and lost, and the call may be missing
    from the run log. One Ctrl-C too many should not do that silently.
    """

    def __init__(self, config, *, runner: Runner, ws: Workspace) -> None:
        super().__init__(config)
        self._runner = runner
        self._ws = ws
        self._warned = False

    def handle_exit(self, sig, frame) -> None:
        if not self._warned and not self.should_exit:
            try:
                active = self._runner.active(self._ws)
            except Exception:
                active = []
            if active:
                self._warned = True
                err_console.print(
                    f"\n[bold yellow]Still running: {_describe(active)}.[/] Ctrl-C again "
                    "to stop the UI; it will wait for that to finish first."
                )
                return
        super().handle_exit(sig, frame)


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
