"""`jobagent jd ...` commands. Thin: read input, call core, render."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from jobagent.adapters import mhtml, pdf
from jobagent.adapters.adtext import ExtractedAd
from jobagent.adapters.llm import CallType, LLMError, get_client
from jobagent.config import get_config
from jobagent.core import store
from jobagent.core.jd import JDError, parse_jd
from jobagent.core.models import JobDescription
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
        None, "--file", "-f", help="Read the JD from a file."
    ),
    stdin: bool = typer.Option(False, "--stdin", help="Read the JD from stdin."),
    source: str | None = typer.Option(
        None, "--source", help="Where it came from, e.g. 'seek', 'recruiter email'."
    ),
) -> None:
    """Parse a job description and save it. Opens $EDITOR if no input is given.

    A saved job page — .mhtml archive or printed .pdf — is detected and
    unwrapped automatically.
    """
    source_url: str | None = None
    source_metadata: str | None = None

    ad = _extract_saved_page(file) if file is not None and not stdin else None
    if ad is not None:
        raw_text = ad.text
        source_url = ad.source_url
        source_metadata = ad.posting_metadata
        console.print(
            f"[dim]Saved page: {len(ad.full_text):,} chars → "
            f"{len(ad.text):,} after removing platform furniture.[/]"
        )
        if source_metadata:
            console.print(f"[dim]Posting: {source_metadata}[/]")
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
    else:
        try:
            raw_text = _read_input(file=file, stdin=stdin)
        except JDError as exc:
            err_console.print(f"[bold red]{exc}[/]")
            raise typer.Exit(code=2)

    config = get_config()

    try:
        client = get_client(CallType.parse_jd, config)
    except LLMError as exc:
        err_console.print(f"[bold red]No model available for JD parsing.[/] {exc}")
        err_console.print("[dim]Run `jobagent config check` to see routing.[/]")
        raise typer.Exit(code=2)

    with console.status("Parsing…"):
        try:
            jd = parse_jd(raw_text, client=client, source=source)
            jd.source_url = source_url
            jd.source_metadata = source_metadata
        except JDError as exc:
            err_console.print(f"[bold red]Could not parse the job description.[/]")
            err_console.print(str(exc))
            raise typer.Exit(code=1)

    try:
        with store.open_store(config.db_path) as conn:
            jd_id = store.add_jd(conn, jd)
    except StoreError as exc:
        err_console.print(f"[bold red]Parsed, but could not save.[/] {exc}")
        raise typer.Exit(code=1)

    jd.id = jd_id
    _render_jd(jd)
    console.print(f"\n[green]Saved as JD {jd_id}.[/]")


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


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #


def _extract_saved_page(file: Path) -> ExtractedAd | None:
    """Unwrap a saved job page, or return None if this is plain text.

    Neither adapter fetches anything; both read the file Alan already saved.
    """
    if mhtml.looks_like_mhtml(file):
        reader, error = mhtml.extract_ad, mhtml.MHTMLError
    elif pdf.looks_like_pdf(file):
        reader, error = pdf.extract_ad, pdf.PDFError
    else:
        return None

    try:
        return reader(file)
    except error as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=2)


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
    header.add_row("location", jd.location or "[dim]not stated[/]")
    header.add_row("work type", jd.work_type.value)
    header.add_row("arrangement", jd.work_arrangement.value)
    header.add_row("seniority", jd.seniority or "[dim]not stated[/]")
    header.add_row("salary", _format_salary(jd))
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
