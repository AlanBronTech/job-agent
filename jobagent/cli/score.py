"""`jobagent score ...`. Thin: resolve config, call core, render."""

from __future__ import annotations

import json
from datetime import date

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from jobagent.adapters.llm import CallType, RunContext, get_client
from jobagent.config import get_config
from jobagent.services import costs, scoring
from jobagent.cli.reapply import overrule_if_asked, refuse
from jobagent.services.refusals import (
    NoModel,
    PossiblySameJob,
    ProfileInvalid,
    ProfileMissing,
    SameJobRecently,
    ThinAd,
)
from jobagent.services.workspace import Workspace
from jobagent.cli.estimate import print_estimate
from jobagent.cli.history import render_company_history
from jobagent.core import history, store
from jobagent.core.models import (
    ConstraintStatus,
    FitAssessment,
    MatchStatus,
    Verdict,
)
from jobagent.core.generate import kind_label
from jobagent.core.scoring import ScoringError
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
    jd_ids: list[int] = typer.Argument(..., help="One or more JD ids, from `jobagent jd list`."),
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
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print the assessment as JSON instead of a table.",
    ),
    overrule_reapply: bool = typer.Option(
        False,
        "--overrule-reapply",
        help="Go ahead even though this is a job you applied for recently. Recorded with the ad.",
    ),
) -> None:
    """Assess job descriptions against the profile and say whether to apply.

    Several ids score each in turn after one combined estimate; an ad that is
    refused (too thin, the same job as a recent application) is reported and
    the rest go ahead.
    """
    if len(jd_ids) == 1:
        _score_one(jd_ids[0], show_last=show_last, force=force, as_json=as_json,
                   overrule_reapply=overrule_reapply)
        return
    if show_last or as_json:
        err_console.print("[bold red]--last and --json take one id at a time.[/]")
        raise typer.Exit(code=2)
    config = get_config()
    estimate = costs.estimate(Workspace.from_config(config), config, "score")
    if estimate.total_usd is not None:
        err_console.print(
            f"[dim]Scoring {len(jd_ids)} ads: about ${estimate.total_usd * len(jd_ids):.2f} "
            f"({costs.describe(estimate)})[/]"
        )
    scored, refused = [], []
    for jd_id in jd_ids:
        console.rule(f"JD {jd_id}")
        try:
            _score_one(jd_id, force=force, overrule_reapply=overrule_reapply)
            scored.append(jd_id)
        except typer.Exit:
            refused.append(jd_id)
    console.print(
        f"\nScored {len(scored)}: {', '.join(map(str, scored)) or 'none'}."
        + (f" Refused {len(refused)}: {', '.join(map(str, refused))}." if refused else "")
    )
    if not scored:
        raise typer.Exit(code=2)


def _score_one(
    jd_id: int,
    show_last: bool = False,
    force: bool = False,
    as_json: bool = False,
    overrule_reapply: bool = False,
) -> None:
    """Score one ad, exactly as `score <id>` always has. Raises typer.Exit on refusal."""
    config = get_config()

    try:
        with store.open_store(config.db_path) as conn:
            jd = store.get_jd(conn, jd_id)
            previous = store.latest_assessment(conn, jd_id) if show_last else None
            stale = store.latest_assessment_stale(conn, jd_id) if show_last else False
            seen_before = history.company_history(conn, jd) if jd else None
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    if jd is None:
        err_console.print(f"[bold red]No job description with id {jd_id}.[/]")
        raise typer.Exit(code=1)

    # Before the refusals and before the model, so it is read whichever way
    # this call ends.
    if seen_before is not None:
        render_company_history(err_console, seen_before)

    if show_last:
        if previous is None:
            err_console.print(f"[bold red]JD {jd_id} has not been scored yet.[/]")
            raise typer.Exit(code=1)
        if stale:
            # The free read is the one most likely to be trusted without
            # thinking, because it costs nothing. An assessment of text that
            # has since been replaced is not wrong — it is about a different
            # ad — and nothing says so unless this does.
            err_console.print(
                f"[bold yellow]This assessment predates an amendment to JD "
                f"{jd_id}[/] and was scored against text that has been "
                f"replaced."
            )
            err_console.print(
                f"[dim]`jobagent score {jd_id}` re-scores against the ad as it "
                f"now stands.[/]"
            )
        try:
            with store.open_store(config.db_path) as conn:
                kind = store.get_role_kind(conn, jd_id)
        except StoreError:
            kind = None
        _emit(jd, previous, as_json=as_json, kind=kind)
        return

    ws = Workspace.from_config(config)
    overrule_if_asked(ws, jd_id, date.today(), overrule_reapply)
    try:
        with console.status("Scoring…"):
            result = scoring.score(
                ws,
                config,
                RunContext(command="score", jd_id=jd.id),
                jd_id,
                force=force,
                before_spend=lambda: print_estimate(config, "score"),
                client_factory=lambda: get_client(
                    CallType.score, config, RunContext(command="score", jd_id=jd.id)
                ),
            )
    except (SameJobRecently, PossiblySameJob) as refusal:
        refuse(err_console, refusal, jd_id, "score")
    except ThinAd as refusal:
        err_console.print(
            f"[bold red]JD {jd_id} holds only {refusal.chars:,} characters "
            "of ad text[/] — too little to score."
        )
        err_console.print(
            "[dim]This is usually a description that was collapsed when the "
            "page was saved. Expand it, save again, and re-add the ad. The "
            "scorer will otherwise read two sentences with the confidence it "
            "reads a whole ad: on JD 23 it assessed five requirements the ad "
            "never stated.[/]"
        )
        err_console.print("[dim]`--force` scores it anyway, for $0.11.[/]")
        raise typer.Exit(code=2)
    except ProfileMissing:
        err_console.print(
            "[bold red]No profile directory.[/] Set PROFILE_DIR in .env."
        )
        raise typer.Exit(code=2)
    except ProfileInvalid as refusal:
        err_console.print(f"[bold red]Profile invalid[/] ({config.profile_dir})")
        err_console.print(refusal.detail)
        raise typer.Exit(code=1)
    except NoModel as refusal:
        err_console.print(f"[bold red]No model available for scoring.[/] {refusal.detail}")
        err_console.print("[dim]Run `jobagent config check` to see routing.[/]")
        raise typer.Exit(code=2)
    except ScoringError as exc:
        err_console.print("[bold red]Could not score this job description.[/]")
        err_console.print(str(exc))
        raise typer.Exit(code=1)

    for warning in result.warnings:
        err_console.print(f"[bold yellow]{warning}[/]")
    assessment = result.assessment
    _emit(jd, assessment, as_json=as_json, kind=result.role_kind)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _emit(jd, fit: FitAssessment, *, as_json: bool, kind=None) -> None:
    """Print the assessment, as a table or as JSON.

    The JSON goes to stdout on its own so the command can be piped. Everything
    conversational — the company history, the refusals — already goes to
    stderr, so `jobagent score 22 --last --json | jq` works unchanged.
    """
    if as_json:
        print(json.dumps(fit.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return
    _render(jd.title, jd.company, fit, requisition_id=jd.requisition_id, kind=kind)


def _render(
    title: str,
    company: str | None,
    fit: FitAssessment,
    *,
    requisition_id: str | None = None,
    kind=None,
) -> None:
    style = _VERDICT_STYLE[fit.verdict]
    verdict = fit.verdict.value.replace("_", " ").upper()

    header = Table.grid(padding=(0, 2))
    header.add_column(style="cyan")
    header.add_column()
    header.add_row("verdict", f"[{style}]{verdict}[/]")
    if requisition_id:
        header.add_row("requisition", requisition_id)
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
    if kind is not None:
        header.add_row("role kind", f"{describe_kind(kind)}  [dim]{kind.reason}[/]")

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
        if check.advisory:
            console.print(f"  [dim]· {check.name} (note, does not decide): {check.detail}[/]")
            continue
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


def describe_kind(kind) -> str:
    """"people-focused (secondary: technical lead)"."""
    text = kind_label(kind.primary)
    if kind.secondary:
        text += f" (secondary: {kind_label(kind.secondary)})"
    return text
