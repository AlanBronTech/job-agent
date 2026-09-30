"""The expected-cost line every paid command prints before it spends.

CLAUDE.md: say what a command will cost before spending it. The figure is the
same one the UI shows, from `services.costs`. It goes to stderr, so `score
--json` still pipes cleanly, and it never stops a command: an estimate that
could not be made is a line saying so, not an error.
"""

from __future__ import annotations

from rich.console import Console

from jobagent.services import costs
from jobagent.services.workspace import Workspace

err_console = Console(stderr=True)


def print_estimate(config, action: str, **selected) -> None:
    try:
        line = costs.describe(
            costs.estimate(Workspace.from_config(config), config, action, **selected)
        )
    except Exception as exc:  # an estimate must never block the work
        line = f"Could not estimate the cost: {exc}"
    err_console.print(f"[dim]{line}[/]")
