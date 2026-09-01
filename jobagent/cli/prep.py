"""`jobagent prep <jd_id>`. Thin: resolve config, call core, render."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from jobagent.adapters import docs
from jobagent.adapters.llm import CallType, LLMError, get_client
from jobagent.config import get_config
from jobagent.core import store
from jobagent.core.models import InterviewPrep
from jobagent.core.prep import PrepError, prepare
from jobagent.core.profile import ProfileError, load_profile
from jobagent.core.store import StoreError
from jobagent.core.validation import Severity, ValidationIssue

console = Console()
err_console = Console(stderr=True)


def prep(
    jd_id: int = typer.Argument(..., help="The JD id, from `jobagent jd list`."),
    interviewer: list[str] = typer.Option(
        [],
        "--interviewer",
        "-i",
        help="Name and role, e.g. 'Sean McCartan, CTO'. Repeatable.",
    ),
    save: bool = typer.Option(
        True,
        "--save/--no-save",
        help="Also write interview-prep.md into the application folder.",
    ),
) -> None:
    """Prepare for an interview: likely questions, mapped to real stories."""
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
            f"Run `jobagent score {jd_id}` first — the hard questions come "
            "from the assessment."
        )
        raise typer.Exit(code=2)
    if config.profile_dir is None:
        err_console.print("[bold red]No profile directory.[/] Set PROFILE_DIR in .env.")
        raise typer.Exit(code=2)

    try:
        profile = load_profile(config.profile_dir)
        client = get_client(CallType.prep, config)
    except (ProfileError, LLMError) as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=2)

    with console.status("Preparing…"):
        try:
            prepared, issues = prepare(
                jd, profile, assessment, client=client, interviewers=list(interviewer)
            )
        except PrepError as exc:
            err_console.print(f"[bold red]Could not prepare.[/] {exc}")
            raise typer.Exit(code=1)

    _render(jd.title, jd.company, prepared, issues)

    if save:
        folder = docs.application_folder(config.output_dir, jd)
        path = docs.write_text(
            folder, "interview-prep.md", _markdown(jd, prepared, issues)
        )
        console.print(f"\n[dim]{path}[/]")


def _render(
    title: str, company: str | None, prep: InterviewPrep, issues: list[ValidationIssue]
) -> None:
    heading = f"Interview prep · {title}" + (f" · {company}" if company else "")
    console.print(Panel(prep.opening or "[dim]no opening supplied[/]", title=heading,
                        title_align="left", border_style="cyan"))

    hard = [q for q in prep.questions if q.hard]
    rest = [q for q in prep.questions if not q.hard]

    if hard:
        console.print("\n[bold red]The hard ones[/] "
                      "[dim]— from the fit assessment, not guesses[/]\n")
        for question in hard:
            _question(question)

    if rest:
        console.print("\n[bold]Also likely[/]\n")
        for question in rest:
            _question(question)

    if prep.questions_to_ask:
        console.print("\n[bold]Ask them[/]\n")
        for item in prep.questions_to_ask:
            console.print(f"  [yellow]·[/] {item}")

    if issues:
        console.print("\n[bold yellow]Validation issues[/]")
        for issue in issues:
            style = "red" if issue.severity is Severity.blocker else "yellow"
            console.print(f"  [{style}]{issue.rule}[/]: {issue.detail}")


def _question(question) -> None:
    console.print(f"  [bold]{question.question}[/]")
    console.print(f"    [dim]{question.why_asked}[/]")
    console.print(f"    {question.answer_outline}")
    if question.story_ref:
        console.print(f"    [cyan]story:[/] {question.story_ref}")
    console.print()


def _markdown(jd, prep: InterviewPrep, issues: list[ValidationIssue]) -> str:
    lines = [
        f"# Interview prep — {jd.title}" + (f" · {jd.company}" if jd.company else ""),
        "",
        f"Prepared {prep.prepared_at:%Y-%m-%d}.",
    ]
    if prep.interviewers:
        lines.append("Interviewers: " + "; ".join(prep.interviewers))
    lines += ["", "## Opening", "", prep.opening, ""]

    for heading, questions in (
        ("The hard ones", [q for q in prep.questions if q.hard]),
        ("Also likely", [q for q in prep.questions if not q.hard]),
    ):
        if not questions:
            continue
        lines += [f"## {heading}", ""]
        for question in questions:
            lines.append(f"### {question.question}")
            lines.append(f"*{question.why_asked}*")
            lines.append("")
            lines.append(question.answer_outline)
            if question.story_ref:
                lines.append(f"\nStory: `{question.story_ref}`")
            lines.append("")

    if prep.questions_to_ask:
        lines += ["## Ask them", ""]
        lines += [f"- {item}" for item in prep.questions_to_ask]
        lines.append("")

    if issues:
        lines += ["## Validation issues", ""]
        lines += [f"- **{i.severity.value}** {i.rule}: {i.detail}" for i in issues]
        lines.append("")

    return "\n".join(lines)
