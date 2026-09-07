"""`jobagent apply`, `outcome` and `status`. Thin: read input, call core, render."""

from __future__ import annotations

from datetime import date, datetime, timezone

import typer
from rich.console import Console
from rich.table import Table

from jobagent.config import get_config
from jobagent.core import store
from jobagent.core.models import Application, ApplicationStatus, Worth
from jobagent.core.store import StoreError

console = Console()
err_console = Console(stderr=True)

_STATUS_STYLE = {
    ApplicationStatus.identified: "dim",
    ApplicationStatus.applied: "cyan",
    ApplicationStatus.applied_no_reply: "dim",
    ApplicationStatus.rejected_screen: "red",
    ApplicationStatus.recruiter_call: "yellow",
    ApplicationStatus.interview_1: "green",
    ApplicationStatus.interview_2: "bold green",
    ApplicationStatus.offer: "bold green",
    ApplicationStatus.withdrew: "dim",
    ApplicationStatus.not_applied: "dim",
}


def apply(
    jd_id: int = typer.Argument(..., help="The JD id, from `jobagent jd list`."),
    on: str | None = typer.Option(
        None, "--on", help="Date applied, YYYY-MM-DD. Defaults to today."
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        help="How it reached you: 'seek', 'linkedin', 'recruiter — Jane Smith'.",
    ),
    note: str = typer.Option("", "--note", help="Anything worth remembering."),
) -> None:
    """Record that you applied for a job."""
    applied_on = _parse_date(on) if on else date.today()
    _save(
        jd_id,
        status=ApplicationStatus.applied,
        applied_on=applied_on,
        channel=channel,
        notes=note,
    )


def outcome(
    jd_id: int = typer.Argument(..., help="The JD id, from `jobagent jd list`."),
    status: ApplicationStatus = typer.Argument(..., help="What became of it."),
    worth: Worth | None = typer.Option(
        None,
        "--worth",
        help="Was applying worth the day, knowing what you know now? This is "
        "what the eval harness grades the scorer against — not the outcome.",
    ),
    why: str = typer.Option("", "--why", help="One line on why. Read in the report."),
    note: str = typer.Option("", "--note", help="Anything worth remembering."),
) -> None:
    """Record what became of an application, and whether it was worth it."""
    _save(jd_id, status=status, worth=worth, worth_why=why, notes=note)


def status_command(
    all: bool = typer.Option(
        False, "--all", help="Include applications that are finished."
    ),
) -> None:
    """Show the pipeline."""
    config = get_config()
    try:
        with store.open_store(config.db_path) as conn:
            applications = store.list_applications(conn)
            jds = {jd.id: jd for jd in store.list_jds(conn)}
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    if not applications:
        console.print(
            "[dim]No applications recorded. `jobagent apply <jd_id>` after you "
            "send one.[/]"
        )
        return

    live = {
        ApplicationStatus.applied,
        ApplicationStatus.recruiter_call,
        ApplicationStatus.interview_1,
        ApplicationStatus.interview_2,
    }
    shown = applications if all else [a for a in applications if a.status in live]
    if not shown:
        console.print(
            f"[dim]Nothing live. {len(applications)} finished application(s) — "
            "pass --all to see them.[/]"
        )
        return

    table = Table(box=None, pad_edge=False)
    table.add_column("jd", style="cyan", justify="right")
    table.add_column("role")
    table.add_column("company")
    table.add_column("status")
    table.add_column("applied", style="dim")
    table.add_column("channel", style="dim")
    table.add_column("worth", style="dim")

    for application in shown:
        jd = jds.get(application.jd_id)
        style = _STATUS_STYLE[application.status]
        table.add_row(
            str(application.jd_id),
            (jd.title if jd else "[dim]missing[/]")[:34],
            ((jd.company or jd.posted_by or "—") if jd else "—")[:22],
            f"[{style}]{application.status.value}[/]",
            application.applied_on.isoformat() if application.applied_on else "—",
            application.channel or "—",
            application.worth_applying.value,
        )
    console.print(table)

    if not all and len(applications) > len(shown):
        console.print(
            f"\n[dim]{len(applications) - len(shown)} finished; --all shows them.[/]"
        )


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #


def _parse_date(value: str) -> date:
    """`--on 2026-09-04` to a date, or a readable refusal.

    Worth its own guard rather than `date.fromisoformat` at the call site: the
    application date feeds `days_to_response`, which outcomes.yaml treats as
    carrying as much signal as the outcome itself — a rejection inside three
    days is automated, one after three weeks was read by a human. A date typed
    wrong, or a future one, corrupts that quietly.
    """
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        err_console.print(
            f"[bold red]Could not read '{value}' as a date.[/] "
            "Use YYYY-MM-DD, as in --on 2026-09-04."
        )
        raise typer.Exit(code=2)
    if parsed > date.today():
        err_console.print(
            f"[bold red]{parsed:%Y-%m-%d} is in the future.[/] "
            "An application date is a record of something that has happened."
        )
        raise typer.Exit(code=2)
    return parsed


def _save(
    jd_id: int,
    *,
    status: ApplicationStatus,
    applied_on: date | None = None,
    channel: str | None = None,
    worth: Worth | None = None,
    worth_why: str = "",
    notes: str = "",
) -> None:
    config = get_config()
    try:
        with store.open_store(config.db_path) as conn:
            jd = store.get_jd(conn, jd_id)
            if jd is None:
                err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
                raise typer.Exit(code=1)

            existing = store.get_application(conn, jd_id)
            application = existing or Application(
                jd_id=jd_id, updated_at=datetime.now(timezone.utc)
            )
            application.status = status
            application.updated_at = datetime.now(timezone.utc)
            if applied_on is not None:
                application.applied_on = applied_on
            if channel is not None:
                application.channel = channel
            if worth is not None:
                application.worth_applying = worth
                # Stated by Alan, so it is no longer an inference from notes.
                application.worth_derived = False
            if worth_why:
                application.worth_why = worth_why
            if notes:
                application.notes = (
                    f"{application.notes}\n{notes}".strip()
                    if application.notes
                    else notes
                )
            store.save_application(conn, application)
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    label = f"{jd.title}" + (f" · {jd.company}" if jd.company else "")
    style = _STATUS_STYLE[status]
    console.print(f"JD {jd_id} [{style}]{status.value}[/]  [dim]{label}[/]")

    if worth is None and status not in {
        ApplicationStatus.identified,
        ApplicationStatus.applied,
    }:
        console.print(
            "\n[dim]No --worth given, so this case is recorded but not graded. "
            "The eval harness needs to know whether applying was worth the day — "
            "which is not the same question as whether they hired you.[/]"
        )
