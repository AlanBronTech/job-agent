"""`jobagent alerts` — SEEK and LinkedIn alert emails, down to the jobs worth a look. Free.

    jobagent alerts                       read new alert emails, list what to look at
    jobagent alerts decide saved 12 15    record what you made of them
    jobagent alerts report                how good the suggestions have been

Reads the emails only; the job pages are never opened (CLAUDE.md, hard rule 1).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from jobagent.adapters import mailbox
from jobagent.config import get_config
from jobagent.core.models import AlertDecision, AlertVerdict
from jobagent.core.store import StoreError
from jobagent.services import alerts
from jobagent.services.refusals import ProfileInvalid, ProfileMissing
from jobagent.services.workspace import Workspace

app = typer.Typer(
    help="Job-alert emails from SEEK and LinkedIn: what is worth a look, and what you decided.",
    invoke_without_command=True,
)
console = Console()
err_console = Console(stderr=True)

# Short forms, so a decision is quick to type.
_ALIASES = {
    "s": "saved", "save": "saved",
    "nr": "not_relevant", "irrelevant": "not_relevant",
    "nq": "not_qualified",
    "ni": "not_interested", "no": "not_interested",
    "aa": "already_applied", "applied": "already_applied",
    "x": "expired", "gone": "expired",
    "l": "later",
}


def _ws() -> Workspace:
    return Workspace.from_config(get_config())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fail(message: str, code: int = 1) -> None:
    err_console.print(f"[bold red]{message}[/]")
    raise typer.Exit(code=code)


@app.callback()
def main(ctx: typer.Context) -> None:
    """With no subcommand: read new alert emails, then list what to look at."""
    if ctx.invoked_subcommand is None:
        fetch(since=None, folder=None)
        list_pending(show_all=False, skipped=False)


@app.command("fetch")
def fetch(
    since: str | None = typer.Option(None, "--since", help="YYYY-MM-DD. Default: the day before the last fetch."),
    folder: Path | None = typer.Option(None, "--dir", help="Read saved .eml files from here instead of Gmail."),
) -> None:
    """Read SEEK and LinkedIn alert emails and judge each job in them."""
    config, ws, now = get_config(), _ws(), _now()
    try:
        start = date.fromisoformat(since) if since else alerts.default_since(ws, now.date())
    except ValueError:
        _fail(f"{since!r} is not a date. Use YYYY-MM-DD.", code=2)
    try:
        if folder is not None:
            result = alerts.ingest(ws, mailbox.read_eml_dir(folder.expanduser(), start), now=now)
        else:
            result = alerts.fetch(
                ws, address=config.gmail_address, app_password=config.gmail_app_password,
                since=start, now=now,
            )
    except alerts.NoMailbox:
        _fail(
            "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env (an app password: Google Account → "
            "Security → 2-Step Verification → App passwords), or use --dir with saved .eml files."
        )
    except alerts.MailboxFailed as refusal:
        _fail(refusal.detail)
    except alerts.NoAlertRules:
        _fail("assets.yaml has no `alerts:` section. See profile.example/assets.yaml.")
    except ProfileMissing:
        _fail("PROFILE_DIR is not set.")
    except ProfileInvalid as refusal:
        _fail(refusal.detail)
    except StoreError as exc:
        _fail(str(exc))
    console.print(
        f"Read {result.emails} alert email(s) since {start:%-d %b}: {result.listings} listing(s), "
        f"{result.new} new. {result.suggested} to look at."
    )
    for subject in result.unread:
        err_console.print(
            f"[yellow]No jobs could be read from “{escape(subject)}”. The email layout may have changed.[/]"
        )


@app.command("list")
def list_pending(
    show_all: bool = typer.Option(False, "--all", help="Every listing, decided or not."),
    skipped: bool = typer.Option(False, "--skipped", help="What the filter left out, and why."),
) -> None:
    """The jobs worth a look that you have not decided on yet."""
    ws, now = _ws(), _now()
    if skipped or show_all:
        rows = alerts.listings(ws, verdict=AlertVerdict.skip if skipped else None)
        for row in rows:
            decided = f" [cyan]{row.decision.value}[/]" if row.decision else ""
            console.print(
                f"{row.id:>4}  {escape(row.title)} — {escape(row.company)}  "
                f"[dim]{row.verdict.value}: {escape(row.reason)}[/]{decided}"
            )
        if not rows:
            console.print("[dim]Nothing.[/]")
        return
    items = alerts.pending(ws, now)
    if not items:
        console.print("[dim]Nothing to look at. `jobagent alerts list --skipped` shows what was left out.[/]")
        return
    heading = None
    for item in items:
        row = item.listing
        label = "Worth a look" if row.verdict is AlertVerdict.suggest else "Maybe"
        if label != heading:
            console.print(f"\n[bold]{label}[/]")
            heading = label
        facts = " · ".join(x for x in (row.company, row.location, row.pay) if x)
        later = " [yellow](later)[/]" if row.decision is AlertDecision.later else ""
        console.print(f"[cyan]{row.id:>4}[/]  [bold]{escape(row.title)}[/] — {escape(facts)}{later}")
        console.print(f"      {row.url}  [dim]{row.source}, seen {row.times_seen}×, {escape(row.reason)}[/]")
        if item.history:
            console.print(f"      [yellow]Before: {escape('; '.join(item.history))}[/]")
    console.print(
        "\n[dim]Then: jobagent alerts decide <decision> ID [ID …] [--note …]\n"
        "  saved (s) · not_relevant (nr) · not_qualified (nq) · not_interested (ni)\n"
        "  already_applied (aa) · expired (x) · later (l)\n"
        "Saving the ad and running `jd add` marks it saved by itself.[/]"
    )


@app.command("decide")
def decide(
    decision: str = typer.Argument(..., help="saved, not_relevant, not_qualified, not_interested, already_applied, expired, later — or s, nr, nq, ni, aa, x, l."),
    listing_ids: list[int] = typer.Argument(..., help="Listing ids from `jobagent alerts`."),
    note: str = typer.Option("", "--note", help="Why, in a few words. Worth it for not_qualified."),
    jd: int | None = typer.Option(None, "--jd", help="The JD it became, if you added it already."),
) -> None:
    """Record what you made of one or more suggested jobs."""
    name = _ALIASES.get(decision.lower(), decision.lower())
    try:
        chosen = AlertDecision(name)
    except ValueError:
        _fail(f"{decision!r} is not a decision. Use one of: {', '.join(d.value for d in AlertDecision)}.", code=2)
    try:
        rows = alerts.decide(_ws(), listing_ids, chosen, note=note, jd_id=jd, now=_now())
    except alerts.NoSuchListing as refusal:
        _fail(f"No alert listing with id {refusal.listing_id}. Nothing was recorded.")
    for row in rows:
        console.print(f"{row.id:>4}  {escape(row.title)} — {escape(row.company)}: [cyan]{chosen.value}[/]")


@app.command("report")
def report() -> None:
    """How the suggestions have fared: what you decided, and what the filter left out."""
    r = alerts.report(_ws())
    if not sum(r.by_verdict.values()):
        console.print("[dim]No alert listings yet. Run `jobagent alerts`.[/]")
        return
    console.print("[bold]Listings and decisions[/]")
    for verdict in ("suggest", "maybe", "skip"):
        counts = r.by_decision.get(verdict, {})
        if counts:
            detail = ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
            console.print(f"  {verdict:<8} {r.by_verdict[verdict]:>4}   {detail}")
    if r.not_relevant:
        console.print("\n[bold]Suggested but not relevant[/] — candidates for never_titles in assets.yaml")
        for row in r.not_relevant[:15]:
            console.print(f"  {escape(row.title)} — {escape(row.company)}  [dim]{escape(row.reason)}[/]")
    if r.not_qualified:
        console.print("\n[bold]Not qualified[/] — a gap recurring here belongs in the profile, or is a real hole")
        for row in r.not_qualified[:15]:
            note = f"  [dim]{escape(row.note)}[/]" if row.note else ""
            console.print(f"  {escape(row.title)} — {escape(row.company)}{note}")
    console.print("\n[bold]Why the filter skipped[/]")
    for reason, n in r.skip_reasons.most_common(12):
        console.print(f"  {n:>4}  {escape(reason)}")
