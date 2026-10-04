"""`jobagent batch` — take in every newly saved ad at once, and see them in one table.

    jobagent batch            free: the new files and what parsing them costs,
                              then the latest batch's table
    jobagent batch parse      parse the new files (or finish the last batch)
    jobagent batch skip 64 65 free: record not_applied for each

Score several with `jobagent score 63 64 65`; generate stays per ad.
"""

from __future__ import annotations

from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from jobagent.adapters.llm import CallType, get_client
from jobagent.config import get_config
from jobagent.core.models import ApplicationStatus
from jobagent.core.store import StoreError
from jobagent.services import batches, costs, pipeline
from jobagent.services.refusals import NoSuchAd
from jobagent.services.workspace import Workspace

app = typer.Typer(help="Take in every newly saved ad at once, as one table.", invoke_without_command=True)
console = Console()
err_console = Console(stderr=True)

_MARK = {"ok": "[green]✓[/]", "breach": "[red]✗[/]", "unknown": "[yellow]?[/]", "note": "[dim]·[/]"}


@app.callback()
def show(ctx: typer.Context) -> None:
    """Free: the new files with the parse cost, then the latest batch."""
    if ctx.invoked_subcommand is not None:
        return
    config = get_config()
    ws = Workspace.from_config(config)
    new = batches.new_files(ws)
    if new:
        console.print(f"[bold]{len(new)} new saved ad(s)[/] in {ws.jd_dir}:")
        for path in new:
            console.print(f"  · {path.name}")
        console.print(f"[dim]{_parse_cost(ws, config, len(new))} Run `jobagent batch parse`.[/]\n")
    latest = batches.latest(ws)
    if latest is None:
        if not new:
            console.print("[dim]Nothing new saved, and no batch yet.[/]")
        return
    _render(ws, latest)


@app.command("parse")
def parse() -> None:
    """Parse the new saved ads (or finish the last batch). Prints the table."""
    config = get_config()
    ws = Workspace.from_config(config)
    batch = batches.latest(ws)
    if batch is None or not batches.waiting(ws, batch):
        batch = batches.start(ws)
    if batch is None:
        console.print("[dim]Nothing new to parse.[/]")
        return
    count = len(batches.waiting(ws, batch))
    try:
        with console.status(f"Parsing {count} ad(s)…"):
            batches.parse(
                ws, config, batch,
                client_factory=lambda ctx: get_client(CallType.parse_jd, config, ctx),
                before_spend=lambda: err_console.print(f"[dim]{_parse_cost(ws, config, count)}[/]"),
            )
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)
    _render(ws, batch)


@app.command("skip")
def skip(ids: list[int] = typer.Argument(..., help="JD ids to record as not applied.")) -> None:
    """Free: record each as not_applied."""
    ws = Workspace.from_config(get_config())
    for jd_id in ids:
        try:
            jd, _ = pipeline.outcome(ws, jd_id, ApplicationStatus.not_applied,
                                     note=f"Not applied: decided at batch review {date.today():%Y-%m-%d}.")
        except NoSuchAd:
            err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
            continue
        console.print(f"JD {jd_id} [dim]not_applied  {jd.title}" + (f" · {jd.company}" if jd.company else "") + "[/]")


# --------------------------------------------------------------------------- #


def _parse_cost(ws: Workspace, config, count: int) -> str:
    estimate = costs.estimate(ws, config, "add_ad")
    if estimate.total_usd is None:
        return f"Parsing {count}: {costs.describe(estimate)}"
    return f"Parsing {count} ad(s): about ${estimate.total_usd * count:.2f} ({costs.describe(estimate)})"


def _render(ws: Workspace, batch_id: int) -> None:
    rows = batches.rows(ws, batch_id, date.today())
    table = Table(title=f"Batch {batch_id}", box=None, pad_edge=False, title_justify="left")
    for name, style in [("#", "dim"), ("JD", "cyan"), ("company / role", ""), ("where", "dim"),
                        ("filters", ""), ("seen", "dim"), ("verdict", ""), ("score", ""), ("state", "")]:
        table.add_column(name, style=style or None)
    for r in rows:
        if r.refusal:
            table.add_row(str(r.number), "—", f"[red]{r.file_name}[/]\n[dim]{batches.describe(r.refusal, r.refusal_detail)}[/]",
                          "", "", "", "", "", "[red]refused[/]")
            continue
        if r.jd_id is None:
            table.add_row(str(r.number), "—", r.file_name, "", "", "", "", "", "[dim]not parsed yet[/]")
            continue
        flags = []
        if r.reapply == "same":
            flags.append("[bold red]same job as an earlier application[/]")
        elif r.reapply == "possibly_same":
            flags.append("[yellow]possibly the same job as an earlier application[/]")
        if r.same_requisition_as:
            flags.append(f"[yellow]same requisition as row {r.same_requisition_as}[/]")
        who = f"{r.company or '—'}\n{r.title}" + ("".join(f"\n{f}" for f in flags))
        if r.requisition_id:
            who += f"\n[dim]{r.requisition_id}[/]"
        where = (r.arrangement or "") + (f"\n{r.salary}" if r.salary else "") + (f"\n{r.posting}" if r.posting else "")
        filters = " ".join(_MARK.get(state, state) for _, state in r.filters)
        score = f"{r.overall_score}/{r.recruiter_score}" if r.overall_score is not None else ""
        table.add_row(str(r.number), str(r.jd_id), who, where, filters,
                      str(r.history_count) if r.history_count else "", (r.verdict or "").replace("_", " "),
                      score, r.state.replace("_", " "))
    console.print(table)
    console.print("[dim]filters: hiring status, work type, location, salary — ✓ met ✗ breach ? not stated · note. "
                  "seen: earlier records at the company. Score several with `jobagent score ID ID …`; "
                  "skip with `jobagent batch skip ID …`.[/]")
