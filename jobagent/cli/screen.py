"""`jobagent screen ID …` — a cheap first pass: is this ad obviously not worth scoring?

About half a cent an ad on the triage route. Advisory: it stores and shows a
decision, and you choose what to score. See core/screen.py.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from jobagent.cli.estimate import print_estimate
from jobagent.config import get_config
from jobagent.services import screening
from jobagent.services.refusals import NoModel, ProfileInvalid, ProfileMissing
from jobagent.services.workspace import Workspace

console = Console()
err_console = Console(stderr=True)


def screen(
    jd_ids: list[int] = typer.Argument(..., help="JD ids to screen."),
    force: bool = typer.Option(False, "--force", help="Screen again even if already screened."),
) -> None:
    """A cheap first pass over parsed ads: obvious skip, or worth scoring."""
    config = get_config()
    run_screen(Workspace.from_config(config), config, jd_ids, force=force)


def run_screen(ws, config, jd_ids: list[int], *, force: bool, show: bool = True) -> list:
    print_estimate(config, "screen")
    try:
        with console.status(f"Screening {len(jd_ids)} ad(s)…"):
            results = screening.screen_ads(ws, config, jd_ids, force=force)
    except ProfileMissing:
        err_console.print("[bold red]No profile directory.[/] Set PROFILE_DIR in .env.")
        raise typer.Exit(code=2)
    except ProfileInvalid as refusal:
        err_console.print(f"[bold red]Profile invalid.[/] {refusal.detail}")
        raise typer.Exit(code=1)
    except NoModel as refusal:
        err_console.print(f"[bold red]No model available for screening.[/] {refusal.detail}")
        raise typer.Exit(code=2)
    if show:
        table = Table(box=None, pad_edge=False)
        for name in ("JD", "company / role", "screen", "why"):
            table.add_column(name)
        for r in results:
            mark = {"skip": "[red]skip[/]", "score": "[green]score[/]"}.get(r.decision, "[yellow]failed[/]")
            if r.reused:
                mark += " [dim](earlier)[/]"
            table.add_row(str(r.jd_id), f"{r.company or '—'}\n{r.title}", mark, r.reason)
        console.print(table)
        keep = [str(r.jd_id) for r in results if r.decision != "skip"]
        if keep:
            console.print(f"[dim]Worth scoring: `jobagent score {' '.join(keep)}`[/]")
    return results
