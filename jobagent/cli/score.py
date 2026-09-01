"""`jobagent score ...`. Thin: resolve config, call core, render."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from jobagent.adapters.llm import CallType, LLMError, get_client
from jobagent.config import get_config
from jobagent.core import store
from jobagent.core.models import (
    ConstraintStatus,
    FitAssessment,
    MatchStatus,
    Verdict,
)
from jobagent.core.profile import ProfileError, load_profile
from jobagent.core.scoring import ScoringError, score_fit
from jobagent.core.store import StoreError

console = Console()
err_console = Console(stderr=True)

_VERDICT_STYLE = {
    Verdict.apply: "bold green",
    Verdict.apply_with_caveats: "bold yellow",
    Verdict.skip: "bold red",
}

_STATUS_MARK = {
    MatchStatus.met: ("[green]✓[/]", ""),
    MatchStatus.partial: ("[yellow]~[/]", "yellow"),
    MatchStatus.gap: ("[red]✗[/]", "red"),
}

_CONSTRAINT_MARK = {
    ConstraintStatus.ok: "[green]✓[/]",
    ConstraintStatus.breach: "[red]✗[/]",
    ConstraintStatus.unknown: "[yellow]?[/]",
}


def score(
    jd_id: int = typer.Argument(..., help="The JD id, from `jobagent jd list`."),
    show_last: bool = typer.Option(
        False,
        "--last",
        help="Show the most recent saved assessment instead of scoring again.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Score even when the ad is too short to conclude anything from.",
    ),
) -> None:
    """Assess one job description against the profile and say whether to apply."""
    config = get_config()

    try:
        with store.open_store(config.db_path) as conn:
            jd = store.get_jd(conn, jd_id)
            previous = store.latest_assessment(conn, jd_id) if show_last else None
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    if jd is None:
        err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
        raise typer.Exit(code=1)

    if show_last:
        if previous is None:
            err_console.print(f"[bold red]JD {jd_id} has not been scored yet.[/]")
            raise typer.Exit(code=1)
        _render(jd.title, jd.company, previous)
        return

    if jd.thin and not force:
        err_console.print(
            f"[bold red]JD {jd_id} holds only {len(jd.raw_text):,} characters "
            "of ad text[/] — too little to score."
        )
        err_console.print(
            "[dim]This is usually a description that was collapsed when the "
            "page was saved. Expand it, save again, and re-add the ad. The "
            "scorer will otherwise read two sentences with the confidence it "
            "reads a whole ad: on JD 23 it assessed five requirements the ad "
            "never stated.[/]"
        )
        err_console.print("[dim]`--force` scores it anyway, for $0.20.[/]")
        raise typer.Exit(code=2)

    if config.profile_dir is None:
        err_console.print(
            "[bold red]No profile directory.[/] Set PROFILE_DIR in .env."
        )
        raise typer.Exit(code=2)

    try:
        profile = load_profile(config.profile_dir)
    except ProfileError as exc:
        err_console.print(f"[bold red]Profile invalid[/] ({config.profile_dir})")
        err_console.print(str(exc))
        raise typer.Exit(code=1)

    try:
        client = get_client(CallType.score, config)
    except LLMError as exc:
        err_console.print(f"[bold red]No model available for scoring.[/] {exc}")
        err_console.print("[dim]Run `jobagent config check` to see routing.[/]")
        raise typer.Exit(code=2)

    with console.status("Scoring…"):
        try:
            assessment = score_fit(jd, profile, client=client)
        except ScoringError as exc:
            err_console.print("[bold red]Could not score this job description.[/]")
            err_console.print(str(exc))
            raise typer.Exit(code=1)

    try:
        with store.open_store(config.db_path) as conn:
            assessment.id = store.add_assessment(conn, assessment)
    except StoreError as exc:
        err_console.print(f"[bold yellow]Scored, but could not save.[/] {exc}")

    _render(jd.title, jd.company, assessment)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _render(title: str, company: str | None, fit: FitAssessment) -> None:
    style = _VERDICT_STYLE[fit.verdict]
    verdict = fit.verdict.value.replace("_", " ").upper()

    header = Table.grid(padding=(0, 2))
    header.add_column(style="cyan")
    header.add_column()
    header.add_row("verdict", f"[{style}]{verdict}[/]")
    header.add_row(
        "score",
        f"{fit.overall_score}/100 hiring manager  ·  "
        f"{fit.recruiter_screen_score}/100 recruiter screen",
    )
    header.add_row(
        "target role",
        ("[green]yes[/] " if fit.target_role_match else "[red]no[/] ")
        + f"[dim]{fit.target_role_note}[/]",
    )

    console.print(
        Panel(
            header,
            title=f"JD {fit.jd_id} · {title}" + (f" · {company}" if company else ""),
            title_align="left",
            border_style=style,
        )
    )
    console.print(f"\n{fit.rationale}\n")

    _render_constraints(fit)
    _render_requirements(fit)
    _render_lines("Lead with", fit.emphasise, numbered=True)
    _render_challenges(fit)
    _render_lines("Ask before applying", fit.questions_to_ask, style="yellow")
    _render_lines("Gaps in the profile itself", fit.profile_gaps, style="dim")

    if fit.model_used:
        console.print(f"\n[dim]{fit.model_used} · {fit.scored_at:%Y-%m-%d %H:%M}[/]")


def _render_constraints(fit: FitAssessment) -> None:
    if not fit.constraints:
        return
    console.print("[bold]Hard filters[/]")
    for check in fit.constraints:
        console.print(f"  {_CONSTRAINT_MARK[check.status]} {check.name}: {check.detail}")
    console.print()


def _render_requirements(fit: FitAssessment) -> None:
    if not fit.requirements:
        return
    met = sum(1 for r in fit.requirements if r.status is MatchStatus.met)
    console.print(f"[bold]Requirements[/] [dim]{met} of {len(fit.requirements)} met[/]")
    for match in fit.requirements:
        mark, colour = _STATUS_MARK[match.status]
        line = f"  {mark} {match.requirement}"
        console.print(f"[{colour}]{line}[/]" if colour else line)
        reference = f" [dim]({match.evidence_ref})[/]" if match.evidence_ref else ""
        console.print(f"      [dim]{match.note}[/]{reference}")
    console.print()


def _render_challenges(fit: FitAssessment) -> None:
    if not fit.challenge_points:
        return
    console.print("[bold]They will push on[/]")
    for challenge in fit.challenge_points:
        console.print(f"  [yellow]·[/] {challenge.point}")
        console.print(f"      [dim]{challenge.response}[/]")
    console.print()


def _render_lines(
    heading: str, items: list[str], *, style: str = "", numbered: bool = False
) -> None:
    if not items:
        return
    console.print(f"[bold]{heading}[/]")
    for index, item in enumerate(items, start=1):
        marker = f"{index}." if numbered else "·"
        console.print(f"  [{style}]{marker}[/] {item}" if style else f"  {marker} {item}")
    console.print()
