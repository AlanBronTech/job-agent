"""`jobagent jd ...` commands. Thin: read input, call core, render."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from jobagent.adapters import docs, mhtml, pdf
from jobagent.adapters.adtext import ExtractedAd
from jobagent.adapters.llm import (
    CallType,
    LLMError,
    RunContext,
    get_client,
    log_attribution,
)
from jobagent.cli import paths
from jobagent.cli.estimate import print_estimate
from jobagent.cli.history import render_company_history
from jobagent.config import get_config
from jobagent.services import ads, reapply
from jobagent.services.refusals import NoSuchAd, UnreadableAd
from jobagent.services.workspace import Workspace
from jobagent.core import history, store
from jobagent.core.jd import JDError, parse_jd
from jobagent.core.models import HiringStatus, JobDescription
from jobagent.core.store import StoreError

app = typer.Typer(help="Ingest and inspect job descriptions.", no_args_is_help=True)

console = Console()
err_console = Console(stderr=True)

_EDITOR_TEMPLATE = """
# Paste the job advertisement below, save, and close the editor.
# Lines beginning with '#' are ignored.
"""


@app.command()
def add(
    file: Path | None = typer.Option(
        None,
        "--file",
        "-f",
        help="A path, or a fragment of a filename in the JD drop folder.",
    ),
    latest: bool = typer.Option(
        False, "--latest", help="Take the most recently saved ad in the drop folder."
    ),
    stdin: bool = typer.Option(False, "--stdin", help="Read the JD from stdin."),
    source: str | None = typer.Option(
        None, "--source", help="Where it came from, e.g. 'seek', 'recruiter email'."
    ),
) -> None:
    """Parse a job description and save it. Opens $EDITOR if no input is given.

    A saved job page — .mhtml archive or printed .pdf — is detected and
    unwrapped automatically.

    `--file` takes a path, or enough of a saved ad's name to identify it:
    `--file ebury` beats quoting 'Engineering Manager (L5_L6) ... .pdf'.
    """
    config = get_config()
    try:
        file = _resolve_file(
            file=file, latest=latest, stdin=stdin, jd_dir=config.jd_dir
        )
    except (JDError, paths.AdNotFound) as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=2)
    if file is not None and not stdin:
        console.print(f"[dim]Reading {file.name}[/]")

    if file is not None and not stdin:
        page = _extract_saved_page(file)
        try:
            ad = ads.AdInput.from_page(page, file.name) if page else ads.read_ad(file=file)
        except UnreadableAd as exc:
            err_console.print(f"[bold red]{exc}[/]")
            raise typer.Exit(code=2)
    else:
        try:
            ad = ads.AdInput(raw_text=_read_input(file=file, stdin=stdin))
        except JDError as exc:
            err_console.print(f"[bold red]{exc}[/]")
            raise typer.Exit(code=2)

    if ad.page_chars is not None:
        console.print(
            f"[dim]Saved page: {ad.page_chars:,} chars → "
            f"{len(ad.raw_text):,} after removing platform furniture.[/]"
        )
        if ad.posting_metadata:
            console.print(f"[dim]Posting: {ad.posting_metadata}[/]")
        if ad.truncated:
            err_console.print(
                "[bold yellow]The description ends at a '…more' toggle — this "
                "capture is incomplete.[/]"
            )
            err_console.print(
                "[dim]Expand the description on the page, save it again, and "
                "re-run. Parsing half an ad gives a confident, wrong answer.[/]"
            )
            raise typer.Exit(code=2)
        if ad.thin_chars is not None:
            err_console.print(
                f"[bold yellow]Only {ad.thin_chars:,} characters of ad text — "
                "this is more likely a collapsed description than a short "
                "advertisement.[/]"
            )
            err_console.print(
                "[dim]If the page has a '…more' toggle, expand it, save again "
                "and re-run. Scoring a stub costs $0.11 to be told the ad is "
                "empty. Continuing anyway.[/]"
            )

    context = RunContext(command="jd add")
    try:
        client = get_client(CallType.parse_jd, config, context)
    except LLMError as exc:
        err_console.print(f"[bold red]No model available for JD parsing.[/] {exc}")
        err_console.print("[dim]Run `jobagent config check` to see routing.[/]")
        raise typer.Exit(code=2)

    try:
        with console.status("Parsing…"):
            result = ads.add(
                Workspace.from_config(config),
                config,
                context,
                ad,
                source=source,
                client=client,
                before_spend=lambda: print_estimate(config, "add_ad"),
            )
    except JDError as exc:
        err_console.print("[bold red]Could not parse the job description.[/]")
        err_console.print(str(exc))
        raise typer.Exit(code=1)
    except StoreError as exc:
        err_console.print(f"[bold red]Parsed, but could not save.[/] {exc}")
        raise typer.Exit(code=1)

    jd, jd_id, seen_before = result.jd, result.jd.id, result.history
    _render_jd(jd)
    console.print(f"\n[green]Saved as JD {jd_id}.[/]")
    # Last, so it is the line still on screen when he decides whether to spend
    # $0.11 scoring it. The company name only exists once the ad is parsed, so
    # this cannot come any earlier than it does.
    render_company_history(err_console, seen_before)


@app.command("amend")
def amend(
    jd_id: int = typer.Argument(..., help="The JD id, from `jobagent jd list`."),
    file: Path | None = typer.Option(
        None,
        "--file",
        "-f",
        help="A path, or a fragment of a filename in the JD drop folder.",
    ),
    latest: bool = typer.Option(
        False, "--latest", help="Take the most recently saved ad in the drop folder."
    ),
    stdin: bool = typer.Option(False, "--stdin", help="Read the new text from stdin."),
    append: bool = typer.Option(
        False,
        "--append",
        help="Add to the stored ad rather than replace it, for a thread that grew.",
    ),
) -> None:
    """Re-parse a stored ad in place when more of it arrives.

    An ad is not immutable. A recruiter answers a question in chat, or the real
    job description turns up a week after the teaser. Both happened inside three
    days, and without this each one forked the role across two records — the
    second holding the better text, the first holding the application, its
    channel and every note.

    `--append` is for a conversation that grew: the stored text and the new text
    are parsed together. The default replaces, which is right when an official
    description supersedes an ad. Either way the previous text is kept.
    """
    config = get_config()
    try:
        file = _resolve_file(
            file=file, latest=latest, stdin=stdin, jd_dir=config.jd_dir
        )
    except (JDError, paths.AdNotFound) as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=2)

    try:
        with store.open_store(config.db_path) as conn:
            existing = store.get_jd(conn, jd_id)
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)
    if existing is None:
        err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
        raise typer.Exit(code=1)

    if file is not None and not stdin:
        console.print(f"[dim]Reading {file.name}[/]")
    ad = _extract_saved_page(file) if file is not None and not stdin else None
    try:
        new_text = ad.text if ad is not None else _read_input(file=file, stdin=stdin)
    except JDError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=2)

    if append:
        new_text = f"{existing.raw_text}\n\n{new_text}"
        console.print("[dim]Appending to the stored ad and re-parsing both.[/]")

    try:
        client = get_client(
            CallType.parse_jd,
            config,
            RunContext(command="jd amend", jd_id=jd_id),
        )
    except LLMError as exc:
        err_console.print(f"[bold red]No model available for JD parsing.[/] {exc}")
        raise typer.Exit(code=2)

    with console.status("Re-parsing…"):
        try:
            parsed = parse_jd(new_text, client=client, source=existing.source)
        except JDError as exc:
            err_console.print("[bold red]Could not parse the new text.[/]")
            err_console.print(str(exc))
            raise typer.Exit(code=1)

    parsed.source_url = existing.source_url
    parsed.source_metadata = existing.source_metadata

    try:
        with store.open_store(config.db_path) as conn:
            store.update_jd(
                conn, jd_id, parsed, amended_at=datetime.now(timezone.utc)
            )
            parsed.id = jd_id
            stale = store.stale_assessments(conn, jd_id)
    except StoreError as exc:
        err_console.print(f"[bold red]Parsed, but could not save.[/] {exc}")
        raise typer.Exit(code=1)

    _render_jd(parsed)
    console.print(f"\n[green]JD {jd_id} amended.[/]")
    _report_changes(existing, parsed)

    if stale:
        err_console.print(
            f"\n[bold yellow]{stale} stored assessment(s) predate this "
            f"amendment[/] and were scored against text that has been replaced."
        )
        err_console.print(
            f"[dim]They are kept — the history is what `eval` reads — but "
            f"`score {jd_id} --last` is now showing an assessment of a "
            f"different ad. Re-score before relying on it.[/]"
        )


def _report_changes(before, after) -> None:
    """Name the fields the re-parse moved.

    The point of an amendment is usually one or two facts — a salary band, a
    work arrangement, a real requirements list. Printing the whole ad again
    buries them.
    """
    fields = [
        ("title", before.title, after.title),
        ("company", before.company, after.company),
        ("location", before.location, after.location),
        ("work type", before.work_type.value, after.work_type.value),
        ("arrangement", before.work_arrangement.value, after.work_arrangement.value),
        ("seniority", before.seniority.value, after.seniority.value),
        ("must-haves", len(before.must_haves), len(after.must_haves)),
        ("responsibilities", len(before.responsibilities), len(after.responsibilities)),
    ]
    changed = [(name, was, now) for name, was, now in fields if was != now]
    if not changed:
        console.print("[dim]No parsed field changed.[/]")
        return
    console.print("\n[bold]Changed[/]")
    for name, was, now in changed:
        console.print(f"  {name}: [dim]{was}[/] → {now}")


@app.command("list")
def list_jds(
    limit: int = typer.Option(20, "--limit", "-n", help="How many to show."),
) -> None:
    """List stored job descriptions, newest first."""
    try:
        with store.open_store(get_config().db_path) as conn:
            jds = store.list_jds(conn, limit=limit)
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    if not jds:
        console.print("[dim]No job descriptions yet. Add one with `jobagent jd add`.[/]")
        return

    table = Table(box=None, pad_edge=False)
    table.add_column("id", style="cyan", justify="right")
    table.add_column("title")
    table.add_column("company")
    table.add_column("location", style="dim")
    table.add_column("type", style="dim")
    table.add_column("added", style="dim")

    for jd in jds:
        table.add_row(
            str(jd.id),
            jd.title,
            jd.company or "—",
            jd.location or "—",
            jd.work_type.value,
            jd.ingested_at.strftime("%Y-%m-%d"),
        )
    console.print(table)


@app.command()
def show(jd_id: int = typer.Argument(..., help="The JD id, from `jobagent jd list`.")) -> None:
    """Show one job description in full."""
    try:
        with store.open_store(get_config().db_path) as conn:
            jd = store.get_jd(conn, jd_id)
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    if jd is None:
        err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
        raise typer.Exit(code=1)

    _render_jd(jd)


@app.command("backfill")
def backfill() -> None:
    """Free: fill in requisition numbers and source files for ads stored before spec 002."""
    report = ads.backfill(Workspace.from_config(get_config()))
    console.print(f"Requisition numbers set: {len(report.requisitions_set)}")
    for jd_id, value in report.requisitions_set:
        console.print(f"  JD {jd_id}  {value}")
    for jd_id, values in report.requisitions_ambiguous:
        console.print(f"  [yellow]JD {jd_id}: several numbers ({', '.join(values)}); none set[/]")
    console.print(f"Source files set: {len(report.files_set)}")
    for jd_id, names in report.files_ambiguous:
        console.print(f"  [yellow]JD {jd_id}: same text in {', '.join(names)}; none set[/]")
    if report.unreadable_files:
        console.print(f"[dim]Unreadable saved files skipped: {', '.join(report.unreadable_files)}[/]")


@app.command("same")
def same(
    jd_id: int = typer.Argument(..., help="The JD id the question was asked about."),
    answer: str = typer.Argument(..., help="yes (same job: the rule applies) or no (a different job)."),
) -> None:
    """Answer "possibly the same job as an earlier application?" for one ad. Free."""
    answer = answer.strip().lower()
    if answer not in {"yes", "no"}:
        err_console.print("[bold red]Answer yes or no.[/]")
        raise typer.Exit(code=2)
    ws = Workspace.from_config(get_config())
    try:
        state = reapply.check(ws, jd_id, date.today())
        matched = state.match.against if hasattr(state, "match") else ""
        reapply.decide(ws, jd_id, "same" if answer == "yes" else "different", matched)
    except NoSuchAd:
        err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
        raise typer.Exit(code=1)
    if answer == "yes":
        console.print(
            f"JD {jd_id}: recorded as the same job. Scoring and generating will be "
            "refused inside the window unless you pass --overrule-reapply."
        )
    else:
        console.print(f"JD {jd_id}: recorded as a different job. It is assessed like any other ad.")


@app.command("delete")
def delete(
    jd_id: int = typer.Argument(..., help="The JD id, from `jobagent jd list`."),
    force: bool = typer.Option(
        False,
        "--force",
        help="Delete even though an application is recorded against it.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """Delete a stored ad, for a duplicate record that should never have existed.

    This is for a genuine duplicate — the same ad ingested twice — not for an
    ad that turned out to be a skip. A skip is a result worth keeping: it is
    what `eval` grades the scorer against, and `history` reads it back when the
    same company posts again.

    Foreign keys cascade, so the assessments go with it. That is the cost, and
    it is reported before anything is removed rather than discovered after.
    Documents already written to OUTPUT_DIR are never touched — two ads can
    resolve to the same folder, so deleting files here could destroy another
    application's documents.
    """
    config = get_config()
    try:
        with store.open_store(config.db_path) as conn:
            jd = store.get_jd(conn, jd_id)
            if jd is None:
                err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
                raise typer.Exit(code=1)

            application = store.get_application(conn, jd_id)
            assessments = store.list_assessments(conn, jd_id)
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    label = f"JD {jd_id} — {jd.title}" + (f" · {jd.company}" if jd.company else "")
    console.print(f"[bold]{label}[/]")

    if application is not None and not force:
        err_console.print(
            f"\n[bold yellow]An application is recorded against this ad.[/] "
            f"Status [bold]{application.status.value}[/], "
            f"{len(application.notes.splitlines())} line(s) of notes."
        )
        err_console.print(
            "\n[dim]Deleting the ad deletes that row with it — the status, the "
            "channel, the worth label and every note. That is the pipeline "
            "record and what `eval` is built from, and none of it is "
            "recoverable. Move the application to the record you are keeping "
            "first, or pass --force if the row is genuinely worthless.[/]"
        )
        raise typer.Exit(code=2)

    console.print("\n[bold]This will remove:[/]")
    console.print(f"  the ad itself, ingested {jd.ingested_at:%-d %B %Y}")
    if assessments:
        console.print(
            f"  [bold yellow]{len(assessments)} assessment(s)[/], by cascade — "
            "a hole in what `eval` reads"
        )
        for item in assessments:
            console.print(
                f"    [dim]{item.scored_at:%Y-%m-%d}  {item.overall_score}/100  "
                f"{item.verdict.value}[/]"
            )
    if application is not None:
        console.print(
            f"  [bold red]the application row[/] ({application.status.value}), "
            "by cascade — forced"
        )

    for folder in docs.folders_for(config.output_dir, jd):
        console.print(
            f"\n[dim]{folder} stays on disk, untouched. Documents are state; "
            "another ad may resolve to the same folder.[/]"
        )

    if not yes:
        console.print()
        if not typer.confirm("Delete it? This cannot be undone"):
            err_console.print("[dim]Left alone.[/]")
            raise typer.Exit(code=1)

    try:
        with store.open_store(config.db_path) as conn:
            removed = store.delete_jd(conn, jd_id)
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    if not removed:
        err_console.print(f"[bold red]Nothing was deleted for id {jd_id}.[/]")
        raise typer.Exit(code=1)

    console.print(f"[bold]Deleted[/] {label}.")


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #


def _extract_saved_page(file: Path) -> ExtractedAd | None:
    """Unwrap a saved job page, or return None if this is plain text."""
    try:
        return ads.extract_saved_page(file)
    except UnreadableAd as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=2)


def _resolve_file(
    *, file: Path | None, latest: bool, stdin: bool, jd_dir: Path
) -> Path | None:
    """Work out which file `add` should read, if any.

    Resolution is skipped when --stdin is set so that the conflicting-input
    error comes from `_read_input`, which words it for the pair given.
    """
    if latest and file is not None:
        raise JDError("Pass either --file or --latest, not both.")
    if stdin:
        return file
    if latest:
        return paths.latest_ad(jd_dir)
    if file is None:
        return None
    return paths.resolve_ad(file, jd_dir)


def _read_input(*, file: Path | None, stdin: bool) -> str:
    if file is not None and stdin:
        raise JDError("Pass either --file or --stdin, not both.")

    if file is not None:
        try:
            return file.read_text(encoding="utf-8")
        except OSError as exc:
            raise JDError(f"Could not read {file}: {exc}") from exc

    if stdin:
        return sys.stdin.read()

    edited = typer.edit(_EDITOR_TEMPLATE, extension=".md")
    if edited is None:
        raise JDError("Editor closed without saving.")
    return "\n".join(
        line for line in edited.splitlines() if not line.lstrip().startswith("#")
    )


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _render_jd(jd: JobDescription) -> None:
    header = Table.grid(padding=(0, 2))
    header.add_column(style="cyan")
    header.add_column()
    header.add_row("company", jd.company or "[dim]not stated[/]")
    if jd.requisition_id:
        header.add_row("requisition", jd.requisition_id)
    if jd.posted_by:
        posted = f"{jd.posted_by} [yellow](agency)[/]" if jd.via_agency else jd.posted_by
        header.add_row("posted by", posted)
    header.add_row("location", jd.location or "[dim]not stated[/]")
    header.add_row("work type", jd.work_type.value)
    header.add_row("arrangement", jd.work_arrangement.value)
    header.add_row("seniority", jd.seniority.value)
    header.add_row("salary", _format_salary(jd))
    if jd.hiring_status is not HiringStatus.unknown:
        status = jd.hiring_status.value
        header.add_row("status", f"[yellow]{status}[/]" if status == "closed" else status)
    if jd.multiple_roles:
        header.add_row("scope", "[yellow]one ad, several unnamed roles[/]")
    if jd.source:
        header.add_row("source", jd.source)
    if jd.source_metadata:
        header.add_row("posting", f"[yellow]{jd.source_metadata}[/]")
    if jd.source_url:
        header.add_row("url", f"[dim]{jd.source_url}[/]")

    title = f"JD {jd.id} · {jd.title}" if jd.id else jd.title
    console.print(Panel(header, title=title, title_align="left"))

    _render_list("Must haves", jd.must_haves)
    _render_list("Nice to haves", jd.nice_to_haves)
    _render_list("Tech stack", jd.tech_stack, inline=True)
    _render_list("Responsibilities", jd.responsibilities)
    _render_list("Red flags", jd.red_flags, style="yellow")


def _format_salary(jd: JobDescription) -> str:
    salary = jd.salary_range
    if salary is None:
        return "[yellow]not stated[/]"
    if salary.min_aud or salary.max_aud:
        low = f"${salary.min_aud:,}" if salary.min_aud else "?"
        high = f"${salary.max_aud:,}" if salary.max_aud else "?"
        suffix = ""
        if salary.includes_super is True:
            suffix = " inc. super"
        elif salary.includes_super is False:
            suffix = " + super"
        return f"{low} – {high}{suffix}"
    return salary.raw or "[yellow]not stated[/]"


def _render_list(
    heading: str, items: list[str], *, inline: bool = False, style: str = ""
) -> None:
    if not items:
        return
    marker = f"[{style}]" if style else ""
    close = f"[/{style}]" if style else ""
    console.print(f"\n[bold]{heading}[/]")
    if inline:
        console.print("  " + ", ".join(items))
        return
    for item in items:
        console.print(f"  {marker}·{close} {item}")
