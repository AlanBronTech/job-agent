"""`jobagent contact` — recruiters and people worth a regular follow-up. Free.

The follow-ups falling due show in `jobagent status`.
"""

from __future__ import annotations

from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from jobagent.config import get_config
from jobagent.core.models import Contact, ContactKind
from jobagent.core.store import StoreError
from jobagent.services import contacts
from jobagent.services.contacts import NoSuchContact
from jobagent.services.refusals import BadDate, NoSuchAd
from jobagent.services.workspace import Workspace

app = typer.Typer(help="Recruiters and contacts, with follow-up reminders.", no_args_is_help=True)
console = Console()
err_console = Console(stderr=True)


def _ws() -> Workspace:
    return Workspace.from_config(get_config())


def _refused(exc: Exception) -> None:
    if isinstance(exc, BadDate):
        err_console.print(f"[bold red]{exc.detail}[/]")
        raise typer.Exit(code=2)
    if isinstance(exc, NoSuchContact):
        err_console.print(f"[bold red]No contact with id {exc.contact_id}.[/] See `jobagent contact list`.")
    elif isinstance(exc, NoSuchAd):
        err_console.print(f"[bold red]No job description with id {exc.jd_id}.[/]")
    else:
        err_console.print(f"[bold red]{exc}[/]")
    raise typer.Exit(code=1)


def _who(c: Contact) -> str:
    return f"{c.name}" + (f", {c.firm}" if c.firm else "")


@app.command("add")
def add(
    name: str = typer.Argument(..., help="The person's name."),
    firm: str = typer.Option("", "--firm", help="Agency or employer."),
    kind: ContactKind = typer.Option(ContactKind.agency_recruiter, "--kind", help="What they are to you."),
    specialty: str = typer.Option("", "--specialty", help="What they place: contract .NET, EM roles, …"),
    channel: str = typer.Option("", "--channel", help="How to reach them: phone, email, LinkedIn."),
    since: str | None = typer.Option(None, "--since", help="First contact, YYYY-MM-DD. Default today."),
    next_: str | None = typer.Option(None, "--next", help="First follow-up: 6w, 10d, 2m or a date. Default 6w."),
    note: str = typer.Option("", "--note", help="Anything worth remembering."),
    jd: int | None = typer.Option(None, "--jd", help="The ad they are connected with, if any."),
) -> None:
    """Add a contact."""
    try:
        first = date.fromisoformat(since) if since else None
    except ValueError:
        err_console.print(f"[bold red]{since!r} is not a date.[/] Use YYYY-MM-DD.")
        raise typer.Exit(code=2)
    try:
        c = contacts.add(
            _ws(), name=name, firm=firm, kind=kind, specialty=specialty, channel=channel,
            first_contact=first, next_followup=next_, notes=note, jd_id=jd,
        )
    except (BadDate, NoSuchAd, StoreError) as exc:
        _refused(exc)
    console.print(f"Added contact {c.id}: {_who(c)}. Follow up {c.next_followup:%a %-d %B %Y}.")


@app.command("list")
def list_contacts() -> None:
    """Every contact, soonest follow-up first."""
    rows = contacts.list_all(_ws())
    if not rows:
        console.print("[dim]No contacts. Add one with `jobagent contact add NAME --firm …`.[/]")
        return
    today = date.today()
    table = Table(box=None, pad_edge=False)
    for column in ("id", "name", "firm", "kind", "specialty", "last touch", "follow up", "jd"):
        table.add_column(column)
    for c in rows:
        follow = f"{c.next_followup:%Y-%m-%d}" if c.next_followup else "—"
        if c.next_followup and c.next_followup <= today:
            follow = f"[bold red]{follow}[/]"
        table.add_row(
            str(c.id), c.name, c.firm or "—", c.kind.value.replace("_", " "), c.specialty or "—",
            f"{c.last_touch:%Y-%m-%d}", follow, str(c.jd_id) if c.jd_id else "—",
        )
    console.print(table)


@app.command("touch")
def touch(
    contact_id: int = typer.Argument(..., help="From `jobagent contact list`."),
    next_: str | None = typer.Option(None, "--next", help="Next follow-up: 6w, 10d, 2m or a date. Default 6w."),
    note: str = typer.Option("", "--note", help="What was said; appended to the notes, dated."),
) -> None:
    """Record a contact made today and set the next follow-up."""
    try:
        c = contacts.touch(_ws(), contact_id, next_followup=next_, note=note)
    except (BadDate, NoSuchContact, StoreError) as exc:
        _refused(exc)
    console.print(f"Touched {_who(c)}. Next follow-up {c.next_followup:%a %-d %B %Y}.")


@app.command("link")
def link(
    contact_id: int = typer.Argument(..., help="From `jobagent contact list`."),
    jd_id: int = typer.Argument(..., help="The ad they are connected with."),
) -> None:
    """Connect a contact with an ad."""
    try:
        c = contacts.link(_ws(), contact_id, jd_id)
    except (NoSuchContact, NoSuchAd, StoreError) as exc:
        _refused(exc)
    console.print(f"Linked {_who(c)} to JD {jd_id}.")


@app.command("show")
def show(contact_id: int = typer.Argument(..., help="From `jobagent contact list`.")) -> None:
    """One contact, with the notes."""
    with_id = [c for c in contacts.list_all(_ws()) if c.id == contact_id]
    if not with_id:
        _refused(NoSuchContact(contact_id))
    c = with_id[0]
    console.print(f"[bold]{_who(c)}[/] ({c.kind.value.replace('_', ' ')})")
    for label, value in (("Specialty", c.specialty), ("Channel", c.channel)):
        if value:
            console.print(f"{label}: {value}")
    console.print(f"First contact {c.first_contact:%Y-%m-%d}, last touch {c.last_touch:%Y-%m-%d}, "
                  + (f"follow up {c.next_followup:%Y-%m-%d}" if c.next_followup else "no follow-up set"))
    if c.jd_id:
        console.print(f"JD {c.jd_id}")
    if c.notes:
        console.print("", c.notes, sep="\n")


def print_due(today: date | None = None) -> None:
    """`jobagent status`'s follow-ups section. Prints nothing when none are due."""
    due = contacts.due(_ws(), today)
    if not due:
        return
    today = today or date.today()
    console.print("\n[bold]Follow-ups due this week[/]")
    for c in due:
        when = "overdue" if c.next_followup < today else f"{c.next_followup:%a %-d %b}"
        if c.next_followup == today:
            when = "today"
        console.print(f"  {c.id:>3}  {_who(c)}  [dim]{when}, last touch {c.last_touch:%-d %b}[/]")
    console.print("[dim]  `jobagent contact touch ID --note …` once done.[/]")
