"""Printing what `services/retention` moved to the bin. Shared by `jd`, `apply` and `batch`."""

from __future__ import annotations

from rich.console import Console

from jobagent.services.retention import KEEP_DAYS, Sweep


def print_sweep(console: Console, sweep: Sweep, *, dry_run: bool = False, show_not_added: bool = False) -> None:
    verb = "Would move" if dry_run else "Moved"
    for item in sweep.binned:
        console.print(f"[dim]{verb} saved ad to the bin (JD {item.jd_id}, {item.reason}): {item.name}[/]")
    for name, problem in sweep.failed:
        console.print(f"[yellow]Not moved: {name}: {problem}[/]")
    if show_not_added and sweep.not_added:
        console.print(f"\n{len(sweep.not_added)} saved ad(s) over {KEEP_DAYS} days old were never added, "
                      "so their text is not in JobAgent. Kept; delete or add them yourself:")
        for name in sweep.not_added:
            console.print(f"  · {name}")
