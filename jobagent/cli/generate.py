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
from jobagent.core.models import ResumeKind
from jobagent.core.store import StoreError
from jobagent.core.validation import Severity, ValidationIssue
from jobagent.services import documents
from jobagent.services.documents import GenerationFailed
from jobagent.services.refusals import (
    AlreadyGenerated,
    MasterProfileMissing,
    NoMasterForProfile,
    NoModel,
    NoSuchAd,
    NotScored,
    ProfileInvalid,
    ProfileMissing,
    SupersedeFailed,
    PossiblySameJob,
    UnknownMaster,
    SameJobRecently,
    VerdictIsSkip,
)
from jobagent.cli.reapply import overrule_if_asked, refuse
from jobagent.services.workspace import Workspace

console = Console()
err_console = Console(stderr=True)


def generate(
    jd_id: int = typer.Argument(..., help="The JD id, from `jobagent jd list`."),
    resume: bool = typer.Option(
        False, "--resume",
        help="A resume: a copy of the suggested master when there is one, else a "
        "generated one. Free with a master.",
    ),
    custom: bool = typer.Option(
        False, "--custom",
        help="Generate a tailored resume (paid), whether or not a master is suggested.",
    ),
    master: str | None = typer.Option(
        None, "--master",
        help="Copy this master (its id in masters.yaml) instead of the suggested one.",
    ),
    no_master: bool = typer.Option(
        False, "--no-master",
        help="Do not copy a master into the job folder.",
    ),
    long_profile: bool = typer.Option(
        False, "--long-profile",
        help="Replace the resume's PROFILE with a longer one (up to 250 words) written "
        "for this ad, for recruitment agencies. With a master (the default), a copy of "
        "the master; with --custom or --no-master, a custom resume. Paid.",
    ),
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
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=50,
        help="Character limit for each answer (with --answers).",
    ),
    no_check_claims: bool = typer.Option(
        False,
        "--no-check-claims",
        help="Skip the paid check of the written prose (resume PROFILE and highlights, letter, answers) against its evidence.",
    ),
    review_flag: bool | None = typer.Option(
        None,
        "--review/--no-review",
        help="Run the paid independent review (~$0.12), or skip it. Default: REVIEW in .env (off).",
    ),
    context: str | None = typer.Option(
        None,
        "--context",
        help="Something you know that the ad does not say ('recruiter said …'). "
        "Kept with the ad and given to every writer; see `jobagent context`.",
    ),
) -> None:
    """Generate application documents for one job description.

    The suggested master resume is copied into the job folder on every run
    unless --no-master: free, and the file to send sits beside the letter.
    """
    if supersede and overwrite:
        err_console.print(
            "[bold red]--supersede and --overwrite contradict each other.[/] "
            "One keeps the earlier documents, the other replaces them."
        )
        raise typer.Exit(code=2)
    if master and no_master:
        err_console.print("[bold red]--master and --no-master contradict each other.[/]")
        raise typer.Exit(code=2)
    if not (resume or custom or master or cover or answers or long_profile):
        err_console.print(
            "[bold red]Nothing to generate.[/] Pass --resume, --custom, --master, "
            "--long-profile, --cover, or --answers."
        )
        raise typer.Exit(code=2)

    if limit is not None and answers is None:
        err_console.print("[bold red]--limit applies to --answers.[/]")
        raise typer.Exit(code=2)

    config = get_config()
    ws = Workspace.from_config(config)
    today = date.today()

    master_id, custom = _which_resume(ws, jd_id, resume=resume or long_profile, custom=custom,
                                      master=master, no_master=no_master)
    resume_kind = None
    if long_profile:
        # Spec 005: the longer PROFILE goes on the master that would be copied,
        # else on a custom resume.
        resume_kind = ResumeKind.custom_profile if custom or master_id is None else ResumeKind.master_profile
        if resume_kind is ResumeKind.custom_profile:
            master_id, custom = None, True
        _say_long_profile(ws, resume_kind, master_id)

    try:
        planned = documents.plan(
            ws, jd_id, resume=custom, cover=cover, answers=answers is not None, when=today,
            master=master_id, resume_kind=resume_kind,
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
    except NoMasterForProfile as refusal:
        err_console.print(
            f"[bold red]No master to copy for this job.[/] {refusal.reason} Pass --master <id>, "
            "or --custom --long-profile."
        )
        raise typer.Exit(code=2)
    except MasterProfileMissing as refusal:
        err_console.print(
            f"[bold red]Cannot place a longer profile in the {refusal.master} master.[/] "
            f"{refusal.detail} Nothing was spent."
        )
        raise typer.Exit(code=2)

    if planned.history is not None:
        render_company_history(err_console, planned.history)

    questions = _read_questions(answers) if answers else []
    overrule_if_asked(ws, jd_id, today, overrule_reapply)
    if context:
        from jobagent.services import revise as revise_service

        revise_service.add_context(ws, jd_id, context, datetime.now())
    check_claims = config.check_claims and not no_check_claims
    review = config.review if review_flag is None else review_flag

    try:
        result = documents.generate(
            ws,
            config,
            RunContext(command="generate", jd_id=jd_id),
            jd_id,
            resume=custom,
            cover=cover,
            questions=questions,
            master=master_id,
            resume_kind=resume_kind,
            overrule=force,
            supersede=supersede,
            overwrite=overwrite,
            today=today,
            now=datetime.now(),
            before_spend=lambda: print_estimate(
                config,
                "generate",
                resume=custom,
                profile=resume_kind is ResumeKind.master_profile,
                cover=cover,
                answers=bool(questions),
                check_claims=check_claims,
                review=review,
                jd_id=jd_id,
            ),
            check_claims=check_claims,
            review=review,
            limit=limit,
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
    except MasterProfileMissing as refusal:
        err_console.print(
            f"[bold red]Cannot place a longer profile in the {refusal.master} master.[/] "
            f"{refusal.detail} Nothing was spent."
        )
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
    _report_coverage(result.coverage)
    if result.copied_only:
        console.print(f"\n[bold]{result.folder}[/]")
        for path in result.written:
            console.print(f"  [green]·[/] {path.name}")
        console.print("\n[dim]Master copied unchanged; nothing was generated, so nothing to review.[/]")
        return
    _report(result.folder, result.written, result.issues, result.unused)
    if result.resume_base is not None and result.resume_base[1]:
        console.print(f"Resume: {documents.describe_base(ws, result.resume_base)}.")
    if result.resume_pages is not None:
        console.print(f"Resume: {result.resume_pages:.2f} pages, measured.")
    if result.copied_only:
        console.print("\n[dim]Master copied unchanged; nothing was generated, so nothing to review.[/]")
        return
    _report_readiness(result)


def _say_long_profile(ws, resume_kind: ResumeKind, master_id: str | None) -> None:
    """Which resume the longer profile goes on, said before anything is spent."""
    from jobagent.services import masters

    if resume_kind is ResumeKind.custom_profile:
        console.print("[bold]Resume:[/] a custom resume with a longer profile (paid).")
        return
    label = next((m.label for m in masters.registry(ws) if m.id == master_id), master_id)
    console.print(
        f"[bold]Resume:[/] copy of the {label} master with a longer profile (paid); "
        "the master itself is not changed."
    )


def _which_resume(ws, jd_id: int, *, resume: bool, custom: bool, master: str | None,
                  no_master: bool) -> tuple[str | None, bool]:
    """(master to copy, generate a custom resume?), and say which, before anything.

    Pick, don't compose (D51): a master is copied whenever one is suggested or
    named. `--resume` is generated only when there is no master list at all.
    """
    from jobagent.core.masters import describe_choice
    from jobagent.services import masters

    registry = masters.registry(ws)
    if master is not None:
        try:
            chosen = masters.find(ws, master)
        except UnknownMaster as exc:
            known = ", ".join(exc.known) or "none"
            err_console.print(f"[bold red]No master called {master!r}.[/] Listed: {known}.")
            raise typer.Exit(code=2)
        console.print(f"[bold]Resume:[/] {chosen.label} master, as asked: "
                      f"{masters.file_to_send(chosen).name}.")
        return chosen.id, custom
    if not registry:
        return None, custom or resume  # no masters: a resume is a generated one
    choice, advice = masters.suggest(ws, jd_id)
    if choice is not None:
        console.print(f"[bold]Resume:[/] {describe_choice(choice)}")
    if advice is not None and advice.recommended is not None:
        console.print(f"  [dim]{advice.reason}[/]")
    suggested = choice.master.id if choice is not None and choice.master is not None else None
    if no_master:
        return None, custom or resume  # a resume without a master is generated
    if resume and suggested is None and not custom:
        err_console.print(
            "[bold red]No master to copy for this job.[/] Pass --master <id> to send one "
            "anyway, or --custom to generate a tailored resume."
        )
        raise typer.Exit(code=2)
    return suggested, custom


_FAILED = {
    "classify": "Could not classify the role.",
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


def _report_readiness(result) -> None:
    """Ready / Not ready / Not reviewed, then the review's findings."""
    from jobagent.services import checks

    reviewed = result.review
    if isinstance(result.claims, checks.NotChecked):
        console.print(f"\n[yellow]Claims not checked:[/] {result.claims.reason}")
    if isinstance(reviewed, checks.Review):
        for title, findings, style in (
            ("Review: blocking", reviewed.blocking, "red"),
            ("Review: suggestions", reviewed.suggestions, "yellow"),
        ):
            if findings:
                console.print(f"\n[bold {style}]{title}[/]")
                for f in findings:
                    console.print(f"  [{style}]·[/] [cyan]{f.document or 'documents'}[/] {f.finding}")
    if result.ready:
        console.print("\n[bold green]Ready[/] [dim]no blockers; the review found nothing blocking.[/]")
    elif reviewed is None or isinstance(reviewed, checks.NotReviewed):
        why = f": {reviewed.reason}" if isinstance(reviewed, checks.NotReviewed) else " (switched off)"
        console.print(f"\n[bold yellow]Not reviewed[/][dim]{why}. Not ready until it is.[/]")
    else:
        console.print("\n[bold red]Not ready[/] [dim]fix the blockers above before sending.[/]")




def _report_coverage(rows) -> None:
    """Each must-have: where the resume answers it, or weak / missing / gap."""
    if not rows:
        return
    console.print("\n[bold]Coverage[/] [dim]must-haves on the resume[/]")
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(ratio=1, min_width=24)
    table.add_column(ratio=1)
    from jobagent.core.coverage import mark

    styles = {"✓": "green", "~": "yellow", "!": "yellow", "✗": "red", "·": "dim"}
    for row in rows:
        symbol, words = mark(row)
        where = f" — {', '.join(row.where)}" if row.where else ""
        table.add_row(row.requirement, f"[{styles[symbol]}]{symbol} {words}[/]{where}")
    console.print(table)


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

    console.print(
        f"\n[bold]Not used[/] [dim]{len(unused)} profile entr(ies) neither cited on the resume "
        "nor matched by their wording; something said in other words is not detected[/]"
    )
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

