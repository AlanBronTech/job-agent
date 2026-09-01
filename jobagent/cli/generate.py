"""`jobagent generate ...`. Thin: resolve config, call core, render, report."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from jobagent.adapters import docs
from jobagent.adapters.docx_writer import (
    CoverLetterContent,
    DocxError,
    write_cover_letter,
    write_resume,
)
from jobagent.adapters.llm import CallType, LLMError, get_client
from jobagent.config import get_config
from jobagent.core import store
from jobagent.core.generate import (
    GenerateError,
    build_answers,
    build_cover_letter,
    build_resume,
)
from jobagent.core.models import JobDescription, Verdict
from jobagent.core.profile import ProfileError, load_profile
from jobagent.core.store import StoreError
from jobagent.core.validation import Severity, ValidationIssue

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
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Generate even when the assessment says skip.",
    ),
) -> None:
    """Generate application documents for one job description."""
    if not (resume or cover or answers):
        err_console.print(
            "[bold red]Nothing to generate.[/] Pass --resume, --cover, or --answers."
        )
        raise typer.Exit(code=2)

    config = get_config()

    try:
        with store.open_store(config.db_path) as conn:
            jd = store.get_jd(conn, jd_id)
            assessment = store.latest_assessment(conn, jd_id) if jd else None
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    if jd is None:
        err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
        raise typer.Exit(code=1)
    if assessment is None:
        err_console.print(
            f"[bold red]JD {jd_id} has not been scored.[/] "
            f"Run `jobagent score {jd_id}` first — generation is shaped by the "
            "assessment."
        )
        raise typer.Exit(code=2)

    if assessment.verdict is Verdict.skip and not force:
        err_console.print(
            f"[bold yellow]The assessment says skip.[/] {assessment.rationale}"
        )
        err_console.print(
            "\n[dim]Generating anyway is a day of work against a role the "
            "scorer has already argued against. Pass --force if you disagree "
            "with it.[/]"
        )
        raise typer.Exit(code=2)

    if config.profile_dir is None:
        err_console.print("[bold red]No profile directory.[/] Set PROFILE_DIR in .env.")
        raise typer.Exit(code=2)

    try:
        profile = load_profile(config.profile_dir)
    except ProfileError as exc:
        err_console.print(f"[bold red]Profile invalid[/] ({config.profile_dir})")
        err_console.print(str(exc))
        raise typer.Exit(code=1)

    try:
        client = get_client(CallType.generate, config)
    except LLMError as exc:
        err_console.print(f"[bold red]No model available for generation.[/] {exc}")
        raise typer.Exit(code=2)

    questions = _read_questions(answers) if answers else []
    today = date.today()
    folder = docs.application_folder(config.output_dir, jd, when=today)
    issues: list[ValidationIssue] = []
    written: list[Path] = []

    if resume:
        with console.status("Selecting content for the resume…"):
            try:
                built = build_resume(jd, profile, assessment, client=client, today=today)
            except GenerateError as exc:
                err_console.print(f"[bold red]Could not build the resume.[/] {exc}")
                raise typer.Exit(code=1)
        issues += built.issues
        try:
            written.append(
                write_resume(
                    built.content, folder / docs.document_name("Resume", jd, when=today)
                )
            )
        except DocxError as exc:
            err_console.print(f"[bold red]{exc}[/]")
            raise typer.Exit(code=1)

    if cover:
        with console.status("Writing the cover letter…"):
            try:
                letter = build_cover_letter(jd, profile, assessment, client=client)
            except GenerateError as exc:
                err_console.print(f"[bold red]Could not write the cover letter.[/] {exc}")
                raise typer.Exit(code=1)
        issues += letter.issues
        content = CoverLetterContent(
            name=profile.roles.person.name,
            contact=_contact(profile),
            date=f"{today:%-d %B %Y}",
            recipient=[jd.company] if jd.company else [],
            paragraphs=[p.strip() for p in letter.text.split("\n\n") if p.strip()],
        )
        try:
            written.append(
                write_cover_letter(
                    content, folder / docs.document_name("CoverLetter", jd, when=today)
                )
            )
        except DocxError as exc:
            err_console.print(f"[bold red]{exc}[/]")
            raise typer.Exit(code=1)

    if questions:
        with console.status("Answering the application questions…"):
            try:
                built_answers = build_answers(
                    questions, jd, profile, assessment, client=client
                )
            except GenerateError as exc:
                err_console.print(f"[bold red]Could not answer the questions.[/] {exc}")
                raise typer.Exit(code=1)
        issues += built_answers.issues
        written.append(docs.write_text(folder, "answers.md", built_answers.text))

    written.append(
        docs.write_text(
            folder, "assessment.md", docs.assessment_markdown(assessment, jd, issues)
        )
    )
    written.append(docs.write_text(folder, "job-ad.md", docs.job_ad_markdown(jd)))

    _report(folder, written, issues)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _report(folder: Path, written: list[Path], issues: list[ValidationIssue]) -> None:
    console.print(f"\n[bold]{folder}[/]")
    for path in written:
        console.print(f"  [green]·[/] {path.name}")

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


def _contact(profile) -> str:
    person = profile.roles.person
    parts = [person.location, person.phone, person.email]
    return "   ·   ".join(part for part in parts if part)
