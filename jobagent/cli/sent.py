"""`jobagent sent` and `jobagent diff` — what went to the employer, and how far
it is from what was generated. Free: no model calls.

`sent` records without touching the application's status, so it can be run
for an application already at interview or rejected; `apply --sent-*` does
the same in one step with recording the application.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from jobagent.adapters.docs import DocsError
from jobagent.adapters.docx_reader import DocxReadError
from jobagent.config import get_config
from jobagent.core.diff import DocumentDiff
from jobagent.core.models import DocumentKind
from jobagent.core.store import StoreError
from jobagent.services import sent as sent_service
from jobagent.services.refusals import (
    NoGeneratedCopy,
    NoSuchAd,
    NothingSent,
    SentFileUnusable,
)
from jobagent.services.workspace import Workspace

console = Console()
err_console = Console(stderr=True)

_LABEL = {DocumentKind.resume: "Resume", DocumentKind.cover_letter: "Cover letter"}


def sent(
    jd_id: int = typer.Argument(..., help="The JD id, from `jobagent jd list`."),
    resume: Path | None = typer.Option(None, "--resume", help="The resume file you sent."),
    letter: Path | None = typer.Option(None, "--letter", help="The cover letter file you sent."),
    as_generated: bool = typer.Option(
        False, "--as-generated", help="You sent the generated documents unedited."
    ),
    generated_resume: Path | None = typer.Option(
        None, "--generated-resume",
        help="The resume as generated, for a folder from before copies were kept.",
    ),
    generated_letter: Path | None = typer.Option(
        None, "--generated-letter",
        help="The cover letter as generated, for a folder from before copies were kept.",
    ),
    on: str | None = typer.Option(None, "--on", help="Date sent, YYYY-MM-DD. Defaults to today."),
) -> None:
    """Record the documents you sent, or list what is recorded."""
    ws = Workspace.from_config(get_config())
    if not (resume or letter or as_generated):
        if generated_resume or generated_letter:
            _refuse("Name the sent file too: --resume or --letter.")
        _list(ws, jd_id)
        return
    record_sent(
        ws, jd_id, resume=resume, letter=letter, as_generated=as_generated,
        generated_resume=generated_resume, generated_letter=generated_letter,
        sent_on=_date(on) if on else date.today(),
    )


def record_sent(ws: Workspace, jd_id: int, *, sent_on: date, **files) -> None:
    """Shared with `apply`: record, then say what was recorded."""
    if files.get("as_generated") and (files.get("resume") or files.get("letter")):
        _refuse("--as-generated records the generated copies. Name no files with it.")
    try:
        rows = sent_service.record(
            ws, jd_id, sent_on=sent_on, today=date.today(), now=datetime.now(), **files
        )
    except NoSuchAd:
        _refuse(f"No job description with id {jd_id}.", code=1)
    except SentFileUnusable as refusal:
        _refuse(f"{refusal.path}: {refusal.reason}.")
    except NoGeneratedCopy as refusal:
        _refuse(
            f"No generated copy is kept in {refusal.folder}. Copies are kept from "
            "2026-10-21 on; for an earlier folder name the files you sent with "
            "--resume/--letter, and the originals with --generated-resume/--generated-letter "
            "if you still have them."
        )
    except (DocsError, StoreError) as exc:
        _refuse(str(exc), code=1)
    for row in rows:
        against = (
            "the generated copy, unedited" if row.as_generated
            else f"compared with {row.generated}" if row.generated
            else "[yellow]no generated copy to compare it with[/]"
        )
        console.print(
            f"{_LABEL[row.kind]}: kept as {escape(row.folder)}/{escape(row.name)} — {against}"
        )


def diff(
    jd_id: int | None = typer.Argument(None, help="The JD id. Omit with --all."),
    all_: bool = typer.Option(False, "--all", help="One line per document sent, every ad."),
    summary: bool = typer.Option(False, "--summary", help="Sections only, no sentences."),
    generated: Path | None = typer.Option(None, "--generated", help="Compare this file …"),
    sent_file: Path | None = typer.Option(None, "--sent", help="… with this one, no records needed."),
    kind: DocumentKind | None = typer.Option(
        None, "--kind", help="With --generated/--sent, if the file names do not say."
    ),
) -> None:
    """How much of each generated document survived into the one you sent."""
    ws = Workspace.from_config(get_config())
    if generated or sent_file:
        _diff_files(generated, sent_file, kind, summary)
        return
    if all_:
        _diff_all(ws)
        return
    if jd_id is None:
        _refuse("Give a JD id, or --all.")
    try:
        comparisons = sent_service.compare_sent(ws, jd_id, date.today())
    except NoSuchAd:
        _refuse(f"No job description with id {jd_id}.", code=1)
    except NothingSent:
        _refuse(
            f"Nothing recorded as sent for JD {jd_id}. "
            f"`jobagent sent {jd_id} --resume FILE --letter FILE` first."
        )
    except StoreError as exc:
        _refuse(str(exc), code=1)
    for comparison in comparisons:
        row = comparison.sent
        console.print(
            f"\n[bold]{_LABEL[row.kind]}[/] sent {row.sent_on:%-d %b %Y}  "
            f"[dim]{escape(row.name)}[/]"
        )
        if comparison.diff is None:
            console.print(f"  [yellow]Not compared: {escape(comparison.problem or '')}.[/]")
            continue
        console.print(f"  [dim]against {escape(row.generated or '')}[/]")
        _render(comparison.diff, summary)


# --------------------------------------------------------------------------- #


def _diff_files(generated, sent_file, kind, summary) -> None:
    if not (generated and sent_file):
        _refuse("--generated and --sent go together.")
    kind = kind or sent_service.kind_of(generated) or sent_service.kind_of(sent_file)
    if kind is None:
        _refuse("Neither file name says resume or cover letter. Pass --kind.")
    try:
        result = sent_service.compare_files(generated.expanduser(), sent_file.expanduser(), kind)
    except DocxReadError as exc:
        _refuse(str(exc), code=1)
    console.print(f"\n[bold]{_LABEL[kind]}[/]  [dim]{escape(generated.name)} → {escape(sent_file.name)}[/]")
    _render(result, summary)


def _diff_all(ws: Workspace) -> None:
    try:
        rows = sent_service.compare_all(ws, date.today())
    except StoreError as exc:
        _refuse(str(exc), code=1)
    if not rows:
        console.print("[dim]Nothing recorded as sent yet.[/]")
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("jd", style="cyan", justify="right")
    table.add_column("company")
    table.add_column("document")
    table.add_column("sent", style="dim")
    table.add_column("kept", justify="right")
    table.add_column("unedited")
    unedited = 0
    for jd, comparison in rows:
        result = comparison.diff
        clean = comparison.sent.as_generated or bool(result and result.unchanged)
        unedited += clean
        table.add_row(
            str(jd.id),
            (jd.company or jd.posted_by or "—")[:22],
            _LABEL[comparison.sent.kind],
            f"{comparison.sent.sent_on:%Y-%m-%d}",
            _share(result.kept_share) if result else "[dim]—[/]",
            "yes" if clean else "no" if result else "[dim]?[/]",
        )
    console.print(table)
    console.print(f"\n{unedited} of {len(rows)} document(s) sent unedited.")


def _render(result: DocumentDiff, summary: bool) -> None:
    if result.unchanged:
        console.print("  [green]Sent exactly as generated.[/]")
        return
    console.print(
        f"  [bold]{_share(result.kept_share)}[/] of generated words kept "
        f"({result.generated_words} generated, {result.sent_words} sent)\n"
    )
    table = Table(box=None, pad_edge=False)
    table.add_column("section")
    table.add_column("words", justify="right", style="dim")
    table.add_column("kept", justify="right")
    table.add_column("changed", justify="right")
    table.add_column("added", justify="right")
    table.add_column("removed", justify="right")
    for section in result.sections:
        table.add_row(
            escape(section.name[:60]),
            str(section.generated_words),
            "new" if section.kept_share is None else _share(section.kept_share),
            _count(section.changed), _count(section.added), _count(section.removed),
        )
    console.print(table)
    if summary:
        return
    for section in result.sections:
        if section.unchanged:
            continue
        lines = (
            [f"  [yellow]~[/] {escape(old)}\n    [yellow]→[/] {escape(new)}" for old, new in section.changed]
            + [f"  [red]−[/] {escape(s)}" for s in section.removed]
            + [f"  [green]+[/] {escape(s)}" for s in section.added]
        )
        if lines:
            console.print(f"\n[bold]{escape(section.name)}[/]")
            for line in lines:
                console.print(line)


def _list(ws: Workspace, jd_id: int) -> None:
    try:
        rows = sent_service.recorded(ws, jd_id)
    except NoSuchAd:
        _refuse(f"No job description with id {jd_id}.", code=1)
    if not rows:
        console.print(
            f"[dim]Nothing recorded as sent for JD {jd_id}. "
            "--resume FILE --letter FILE, or --as-generated.[/]"
        )
        return
    for row in rows:
        mark = " (as generated)" if row.as_generated else ""
        console.print(
            f"{row.sent_on:%Y-%m-%d}  {_LABEL[row.kind]:<12}  "
            f"{escape(row.folder)}/{escape(row.name)}{mark}"
        )


def _share(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _count(items) -> str:
    return str(len(items)) if items else "[dim]0[/]"


def _date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        _refuse(f"Could not read '{value}' as a date. Use YYYY-MM-DD.")
    if parsed > date.today():
        _refuse(f"{parsed:%Y-%m-%d} is in the future.")
    return parsed


def _refuse(message: str, *, code: int = 2):
    err_console.print(f"[bold red]{escape(message)}[/]")
    raise typer.Exit(code=code)
