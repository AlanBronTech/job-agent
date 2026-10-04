"""`jobagent outside` — applications made without an ad in the store.

Before the tool existed, or straight through a portal. Recording one makes it
count for company history and the six-month rule (spec 002, US3). Free.
"""

from __future__ import annotations

from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from jobagent.config import get_config
from jobagent.core.models import ApplicationStatus
from jobagent.core.store import StoreError
from jobagent.services import applications
from jobagent.services.applications import NoSuchOutside
from jobagent.services.refusals import BadDate, NoSuchAd
from jobagent.services.workspace import Workspace

app = typer.Typer(help="Applications made outside the tool, with no ad stored.", no_args_is_help=True)
console = Console()
err_console = Console(stderr=True)


@app.command("add")
def add(
    company: str = typer.Option(..., "--company", help="Employer, as you would name it."),
    title: str = typer.Option(..., "--title", help="Role title applied for."),
    on: str = typer.Option(..., "--on", help="Date applied, YYYY-MM-DD."),
    req: str | None = typer.Option(None, "--req", help="Requisition or reference number, if known."),
    channel: str | None = typer.Option(None, "--channel", help="How it was sent: careers site, recruiter, …"),
    status: ApplicationStatus = typer.Option(
        ApplicationStatus.applied, "--status", help="Where it stands now."
    ),
    note: str = typer.Option("", "--note", help="Anything worth remembering."),
) -> None:
    """Record an application made outside the tool."""
    try:
        applied_on = date.fromisoformat(on)
    except ValueError:
        err_console.print(f"[bold red]{on!r} is not a date.[/] Use YYYY-MM-DD.")
        raise typer.Exit(code=2)
    try:
        record = applications.record_outside(
            Workspace.from_config(get_config()),
            company=company, title=title, applied_on=applied_on, requisition_id=req,
            channel=channel, status=status, notes=note,
        )
    except BadDate as refusal:
        err_console.print(f"[bold red]{refusal.detail}[/]")
        raise typer.Exit(code=2)
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)
    console.print(
        f"Recorded outside application {record.id}: {record.company}, {record.title}, "
        f"applied {record.applied_on:%-d %B %Y}"
        + (f", requisition {record.requisition_id}" if record.requisition_id else "")
        + f" ({record.status.value})."
    )


@app.command("list")
def list_outside() -> None:
    """Every application recorded outside the tool, newest first."""
    records = applications.list_outside(Workspace.from_config(get_config()))
    if not records:
        console.print("[dim]None recorded. Add one with `jobagent outside add`.[/]")
        return
    table = Table(box=None, pad_edge=False)
    for column in ("id", "applied", "company", "title", "requisition", "status", "linked"):
        table.add_column(column)
    for r in records:
        table.add_row(
            str(r.id), f"{r.applied_on:%Y-%m-%d}", r.company, r.title, r.requisition_id or "—",
            r.status.value, f"JD {r.linked_jd_id}" if r.linked_jd_id else "—",
        )
    console.print(table)


@app.command("link")
def link(
    outside_id: int = typer.Argument(..., help="From `jobagent outside list`."),
    jd_id: int = typer.Argument(..., help="The stored ad for the same application."),
) -> None:
    """Make a stored ad's application the record of an outside one."""
    try:
        application = applications.link_outside(Workspace.from_config(get_config()), outside_id, jd_id)
    except NoSuchOutside:
        err_console.print(f"[bold red]No outside application with id {outside_id}.[/]")
        raise typer.Exit(code=1)
    except NoSuchAd:
        err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
        raise typer.Exit(code=1)
    console.print(
        f"Linked: JD {jd_id} now records the application of "
        f"{application.applied_on:%-d %B %Y} ({application.status.value})."
    )
