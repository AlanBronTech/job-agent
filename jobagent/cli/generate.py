"""`jobagent generate ...`. Thin: parse arguments, call services.documents, report."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from jobagent.adapters.llm import RunContext
from jobagent.cli import paths
from jobagent.cli.estimate import print_estimate
from jobagent.cli.history import render_company_history
from jobagent.config import get_config
from jobagent.core.generate import UnusedEntry
from jobagent.core.store import StoreError
from jobagent.core.validation import Severity, ValidationIssue
from jobagent.services import documents
from jobagent.services.documents import GenerationFailed
from jobagent.services.refusals import (
    AlreadyGenerated,
    NoModel,
    NoSuchAd,
    NotScored,
    ProfileInvalid,
    ProfileMissing,
    SupersedeFailed,
    PossiblySameJob,
    SameJobRecently,
    VerdictIsSkip,
)
from jobagent.cli.reapply import overrule_if_asked, refuse
from jobagent.services.workspace import Workspace

console = Console()
err_console = Console(stderr=True)


def generate(
    jd_id: int = typer.Argument(..., help="The JD id, from `jobagent jd list`."),
    resume: bool = typer.Option(False, "--resume", help="Write a tailored resume."),
    cover: bool = typer.Option(False, "--cover", help="Write a cover letter."),
    answers: Path | None = typer.Option(
        None,
        "--answers",
        help="File of application questions, one per line, to answer.",
        callback=paths.expand,
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Generate even when the assessment says skip.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Replace documents already generated for this application.",
    ),
    supersede: bool = typer.Option(
        False,
        "--supersede",
        help="Keep documents already generated: move their folder aside under a "
        "dated name, then write a fresh one.",
    ),
    overrule_reapply: bool = typer.Option(
        False,
        "--overrule-reapply",
        help="Go ahead even though this is a job you applied for recently. Recorded with the ad.",
    ),
) -> None:
    """Generate application documents for one job description."""
    if supersede and overwrite:
        err_console.print(
            "[bold red]--supersede and --overwrite contradict each other.[/] "
            "One keeps the earlier documents, the other replaces them."
        )
        raise typer.Exit(code=2)
    if not (resume or cover or answers):
        err_console.print(
            "[bold red]Nothing to generate.[/] Pass --resume, --cover, or --answers."
        )
        raise typer.Exit(code=2)

    config = get_config()
    ws = Workspace.from_config(config)
    today = date.today()

    try:
        planned = documents.plan(
            ws, jd_id, resume=resume, cover=cover, answers=answers is not None, when=today
        )
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)
    except NoSuchAd:
        err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
        raise typer.Exit(code=1)
    except NotScored:
        err_console.print(
            f"[bold red]JD {jd_id} has not been scored.[/] "
            f"Run `jobagent score {jd_id}` first — generation is shaped by the "
            "assessment."
        )
        raise typer.Exit(code=2)

    if planned.history is not None:
        render_company_history(err_console, planned.history)

    questions = _read_questions(answers) if answers else []
    overrule_if_asked(ws, jd_id, today, overrule_reapply)

    try:
        result = documents.generate(
            ws,
            config,
            RunContext(command="generate", jd_id=jd_id),
            jd_id,
            resume=resume,
            cover=cover,
            questions=questions,
            overrule=force,
            supersede=supersede,
            overwrite=overwrite,
            today=today,
            now=datetime.now(),
            before_spend=lambda: print_estimate(
                config, "generate", resume=resume, cover=cover, answers=bool(questions)
            ),
        )
    except (SameJobRecently, PossiblySameJob) as refusal:
        refuse(err_console, refusal, jd_id, "generate")
    except VerdictIsSkip as refusal:
        err_console.print(f"[bold yellow]The assessment says skip.[/] {refusal.rationale}")
        err_console.print(
            "\n[dim]Generating anyway is a day of work against a role the "
            "scorer has already argued against. Pass --force if you disagree "
            "with it.[/]"
        )
        raise typer.Exit(code=2)
    except SupersedeFailed as refusal:
        err_console.print(
            f"[bold red]Could not move {config.output_dir / refusal.folder} aside.[/] "
            f"{refusal.reason} Nothing was spent and the folder is untouched."
        )
        raise typer.Exit(code=1)
    except AlreadyGenerated as refusal:
        _refuse_to_clobber(config.output_dir / refusal.folder, refusal.files)
    except ProfileMissing:
        err_console.print("[bold red]No profile directory.[/] Set PROFILE_DIR in .env.")
        raise typer.Exit(code=2)
    except ProfileInvalid as refusal:
        err_console.print(f"[bold red]Profile invalid[/] ({config.profile_dir})")
        err_console.print(refusal.detail)
        raise typer.Exit(code=1)
    except NoModel as refusal:
        err_console.print(f"[bold red]No model available for generation.[/] {refusal.detail}")
        raise typer.Exit(code=2)
    except GenerationFailed as failure:
        err_console.print(f"[bold red]{_FAILED[failure.stage]}[/] {failure.cause}")
        if failure.written:
            err_console.print(
                "[yellow]Written before it failed, so incomplete:[/] "
                + ", ".join(path.name for path in failure.written)
            )
        raise typer.Exit(code=1)

    for warning in result.warnings:
        err_console.print(f"[yellow]{warning}[/]")
    if result.superseded is not None:
        console.print(f"[dim]Earlier documents kept in {config.output_dir / result.superseded}[/]")
    _report(result.folder, result.written, result.issues, result.unused)


_FAILED = {
    "resume": "Could not build the resume.",
    "cover": "Could not write the cover letter.",
    "answers": "Could not answer the questions.",
    "write": "Could not write the documents.",
}


def _refuse_to_clobber(folder: Path, files: list[tuple[str, datetime]]) -> None:
    """Stop before spending anything: this run would overwrite earlier work.

    Checked before the model is called, because by then the calls have been
    paid for and the only choice left is to bin the result or bin the earlier
    documents. The generated .docx files are the ones that get edited by hand
    and sent to an employer; regenerating them from the same profile
    reproduces the substance but not the edits.
    """
    newest = max(modified for _, modified in files)
    err_console.print(
        f"[bold yellow]Already generated.[/] {folder} holds documents for this "
        f"application, most recently "
        f"{newest:%-d %B %Y at %H:%M}."
    )
    for name, modified in files:
        err_console.print(f"  [dim]{modified:%Y-%m-%d %H:%M}[/]  {name}")
    err_console.print(
        "\n[dim]Re-running would replace these in place, including any edits "
        "made by hand since. Move or rename the folder to keep them, pass "
        "--supersede to keep them under a dated name, or pass --overwrite to "
        "replace them.[/]"
    )
    raise typer.Exit(code=2)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _report(
    folder: Path,
    written: list[Path],
    issues: list[ValidationIssue],
    unused: list[UnusedEntry] | None = None,
) -> None:
    console.print(f"\n[bold]{folder}[/]")
    for path in written:
        console.print(f"  [green]·[/] {path.name}")

    _report_issues(issues)
    _report_unused(unused or [])


def _report_unused(unused: list[UnusedEntry]) -> None:
    """Profile entries the model used nowhere.

    Printed every run, after the validation result, and deliberately not a
    warning: which evidence an ad rewards is the model's judgement and usually
    it is right. It exists because an omission is invisible in a finished
    document — DataLlama was dropped from a resume twice, and both times the
    only way to notice was to already know it should have been there. A
    validator cannot decide this; a reader can, and only while still reading.
    """
    if not unused:
        return

    console.print(f"\n[bold]Not used[/] [dim]{len(unused)} profile entr(ies)[/]")
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    for entry in unused:
        notes = []
        if entry.strong:
            notes.append("strong evidence")
        if entry.highlight_only:
            notes.append("ongoing venture — a CAREER HIGHLIGHT is its only slot")
        suffix = f"  [yellow]({'; '.join(notes)})[/]" if notes else ""
        table.add_row(entry.id, f"{entry.label}{suffix}")
    console.print(table)
    console.print(
        "[dim]Selection is the model's call and is usually right. Check this "
        "list against the ad before sending, not after.[/]"
    )


def _report_issues(issues: list[ValidationIssue]) -> None:
    if not issues:
        console.print("\n[green]No validation issues.[/]")
        return

    blocking = [issue for issue in issues if issue.severity is Severity.blocker]
    heading = "[bold red]Blockers[/]" if blocking else "[bold yellow]Warnings[/]"
    console.print(f"\n{heading} [dim]{len(issues)} issue(s)[/]")

    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    for issue in issues:
        style = "red" if issue.severity is Severity.blocker else "yellow"
        detail = issue.detail + (f"\n[dim]{issue.excerpt}[/]" if issue.excerpt else "")
        table.add_row(f"[{style}]{issue.rule}[/]", detail)
    console.print(table)

    if blocking:
        console.print(
            "\n[red]Do not send these without fixing the blockers.[/] "
            "[dim]An unsupported number means the claim is either invented or "
            "missing from the profile — check which before editing.[/]"
        )


def _read_questions(path: Path) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        err_console.print(f"[bold red]Could not read {path}: {exc}[/]")
        raise typer.Exit(code=2)
    return [line.strip() for line in raw.splitlines() if line.strip()]

