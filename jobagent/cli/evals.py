"""`jobagent eval ...`. Thin: resolve config, call core, render."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from jobagent.adapters.llm import (
    CallType,
    LLMError,
    QuotaExhaustedError,
    RunContext,
    get_client,
)
from jobagent.cli import paths
from jobagent.config import get_config
from jobagent.core import store
from jobagent.core.evals import (
    CaseResult,
    EvalCase,
    EvalError,
    EvalReport,
    build_report,
    cases_from_applications,
    diff_runs,
    load_cases,
)
from jobagent.core.models import Verdict, Worth
from jobagent.core.profile import ProfileError, load_profile
from jobagent.core.scoring import ScoringError, score_fit
from jobagent.core.store import StoreError

app = typer.Typer(
    help="Measure the fit scorer against applications with known outcomes.",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)

# Measured over 63 real scoring calls, not estimated: ~26k input tokens (the
# whole profile goes in every call) and 6-9k out, at Sonnet 5's $2/$10 per
# million. Was 0.19 while the price table carried Sonnet 4.6's $3/$15.
COST_PER_CASE_USD = 0.11

_VERDICT_STYLE = {
    Verdict.apply: "green",
    Verdict.apply_with_caveats: "yellow",
    Verdict.skip: "red",
}

_AGREEMENT_STYLE = {
    "agree — apply": "green",
    "agree — skip": "green",
    "false positive": "red",
    "false negative": "bold red",
    "unlabelled": "dim",
    "unscored": "dim",
}


@app.command("report")
def report(
    cases_path: Path | None = typer.Option(
        None, "--cases", help="Case set to read.", callback=paths.expand
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Grade the latest run from this model, e.g. 'claude-sonnet-5'. "
        "Without it, whatever was scored last wins — including a cheap "
        "comparison run.",
    ),
) -> None:
    """Grade the stored assessments against the recorded outcomes. Free."""
    cases, results = _load(cases_path, model=model)
    if not any(result.scored for result in results):
        err_console.print(
            "[bold yellow]No case has been scored yet.[/] Run `jobagent eval run`."
        )
        raise typer.Exit(code=1)
    _render_report(build_report(results))


@app.command("run")
def run(
    cases_path: Path | None = typer.Option(
        None, "--cases", help="Case set to read.", callback=paths.expand
    ),
    only: str | None = typer.Option(None, "--only", help="Score one case by id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost confirmation."),
) -> None:
    """Score every case again, then grade. Costs money — it calls the API."""
    cases, _ = _load(cases_path)
    if only:
        cases = [case for case in cases if case.id == only]
        if not cases:
            err_console.print(f"[bold red]No case with id {only!r}.[/]")
            raise typer.Exit(code=1)

    config = get_config()
    if config.budget_mode:
        console.print(
            f"Scoring {len(cases)} case(s) in [bold yellow]budget mode[/] via "
            f"[bold]{config.budget_model}[/] — free tier, so the run costs "
            "nothing but the answers will be worse. `eval diff` afterwards "
            "says by how much."
        )
    else:
        estimate = len(cases) * COST_PER_CASE_USD
        console.print(
            f"Scoring {len(cases)} case(s). Estimated cost "
            f"[bold]${estimate:.2f}[/] [dim](~${COST_PER_CASE_USD:.2f} each; the "
            f"whole profile is sent with every call)[/] "
            "[dim]— `--budget` runs it free on Gemini instead.[/]"
        )
    if not yes and not typer.confirm("Continue?", default=False):
        raise typer.Exit(code=1)

    if config.profile_dir is None:
        err_console.print("[bold red]No profile directory.[/] Set PROFILE_DIR in .env.")
        raise typer.Exit(code=2)
    try:
        profile = load_profile(config.profile_dir)
        client = get_client(
            CallType.score,
            config,
            RunContext(command="eval run", source="eval"),
        )
    except (ProfileError, LLMError) as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=2)

    results: list[CaseResult] = []
    failures: list[tuple[str, str]] = []
    with store.open_store(config.db_path) as conn:
        for index, case in enumerate(cases, 1):
            jd = store.get_jd(conn, case.jd_id)
            if jd is None:
                failures.append((case.id, f"JD {case.jd_id} is not in the store"))
                continue
            # One client, many cases: the context says which case each
            # call belongs to, so eval spend is attributable per JD too.
            client.context.jd_id = case.jd_id
            label = f"[{index}/{len(cases)}] {case.id}"
            with console.status(f"{label} — scoring…"):
                try:
                    assessment = score_fit(jd, profile, client=client)
                except ScoringError as exc:
                    failures.append((case.id, str(exc)))
                    console.print(f"{label} [red]failed[/]")
                    if isinstance(exc.__cause__, QuotaExhaustedError):
                        err_console.print(
                            f"\n[bold yellow]Stopping.[/] {exc.__cause__} "
                            f"\n[dim]{len(results)} case(s) scored before the "
                            "allowance ran out; they are saved.[/]"
                        )
                        break
                    continue
                assessment.id = store.add_assessment(conn, assessment)
            style = _VERDICT_STYLE[assessment.verdict]
            console.print(
                f"{label} [{style}]{assessment.verdict.value}[/] "
                f"{assessment.overall_score}/100"
            )
            results.append(CaseResult(case=case, assessment=assessment))

    if failures:
        err_console.print("\n[bold red]Failed[/]")
        for case_id, reason in failures:
            err_console.print(f"  {case_id}: {reason}")

    if results:
        console.print()
        _render_report(build_report(results))


@app.command("export")
def export(
    to: Path = typer.Option(
        Path("evals/cases.yaml"),
        "--to",
        help="Where to write the snapshot.",
        callback=paths.expand,
    ),
) -> None:
    """Write the case set out as YAML — a reviewable, diffable snapshot."""
    import yaml

    cases, _ = _load(None)
    payload = [
        {
            "id": case.id,
            "jd_id": case.jd_id,
            "outcome": case.outcome.value,
            "worth_applying": case.worth_applying.value,
            "why": case.why,
        }
        for case in cases
    ]
    to.parent.mkdir(parents=True, exist_ok=True)
    to.write_text(
        "# Snapshot of the eval set, exported from the pipeline.\n"
        "# The store is the source of truth; this file is for review and for\n"
        "# replaying a fixed set with `jobagent eval report --cases`.\n"
        + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    console.print(f"{len(cases)} case(s) → {to}")


@app.command("diff")
def diff(
    cases_path: Path | None = typer.Option(
        None, "--cases", help="Case set to read.", callback=paths.expand
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Compare runs from this model only, e.g. 'claude-sonnet-5'.",
    ),
) -> None:
    """Compare the two most recent scoring runs. Free.

    This is the prompt-regression view: edit `prompts/score_fit.md`, run
    `eval run`, then this shows what the edit actually changed.

    Without `--model` the two newest runs for each case are compared whatever
    produced them, so one cheap comparison run in between turns a prompt diff
    into a provider diff. That happened: twelve of fourteen cases were read
    against a Gemini run and reported swings of fifty points. The comparison
    now names the models it used, and says so when they differ.
    """
    cases, _ = _load(cases_path)
    config = get_config()

    diffs = []
    try:
        with store.open_store(config.db_path) as conn:
            for case in cases:
                history = store.list_assessments(conn, case.jd_id, model=model)
                changed = diff_runs(case.id, history)
                if changed is not None:
                    diffs.append(changed)
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    if not diffs:
        console.print(
            "[dim]No case has been scored twice yet — nothing to compare.[/]"
        )
        return

    moved = [d for d in diffs if d.changed]
    console.print(
        f"[bold]{len(moved)} of {len(diffs)}[/] case(s) changed between the "
        "last two runs.\n"
    )
    _report_models(diffs)
    if not moved:
        return

    table = Table(box=None, pad_edge=False)
    table.add_column("case", style="cyan")
    table.add_column("verdict")
    table.add_column("score", justify="right")
    table.add_column("screen", justify="right")
    table.add_column("reqs", justify="right")
    table.add_column("met", justify="right")

    for change in moved:
        verdict = (
            f"[yellow]{change.before.verdict.value} → {change.after.verdict.value}[/]"
            if change.verdict_changed
            else "[dim]unchanged[/]"
        )
        table.add_row(
            change.case_id,
            verdict,
            _delta(change.score_delta),
            _delta(change.screen_delta),
            _delta(change.requirement_delta),
            _delta(change.met_delta),
        )
    console.print(table)


def _report_models(diffs: list) -> None:
    """Name the models compared, and warn when a case crossed providers.

    A diff that silently spans two models reads as a prompt regression and is
    not one. Naming them makes the mistake visible in the output itself.
    """
    mixed = [d for d in diffs if d.before.model_used != d.after.model_used]
    models = sorted(
        {m for d in diffs for m in (d.before.model_used, d.after.model_used) if m}
    )
    console.print(f"[dim]Comparing: {', '.join(models) or 'model not recorded'}[/]")
    if mixed:
        err_console.print(
            f"[bold yellow]{len(mixed)} of {len(diffs)} case(s) compare two "
            "different models[/] — this is a provider difference, not a prompt "
            "one."
        )
        err_console.print(
            "[dim]Pass --model to compare like with like, e.g. "
            "`jobagent eval diff --model claude-sonnet-5`.[/]\n"
        )


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _render_report(report: EvalReport) -> None:
    _render_cases(report)

    console.print("\n[bold]Graded against 'was this worth applying to'[/]")
    if report.labelled:
        console.print(
            f"  agreed on [bold]{report.agree}[/] of {report.labelled} labelled "
            f"case(s)"
            + (f"  [dim]({report.accuracy:.0%})[/]" if report.accuracy else "")
        )
    else:
        console.print("  [dim]no case carries a worth_applying label yet[/]")

    if report.false_negatives:
        console.print(
            f"\n  [bold red]{len(report.false_negatives)} false negative(s)[/] "
            "— said skip, was worth applying to. [dim]The expensive error: an "
            "opportunity that does not come back.[/]"
        )
        for result in report.false_negatives:
            console.print(f"    [red]·[/] {result.case.id} — {result.case.why}")

    if report.false_positives:
        console.print(
            f"\n  [red]{len(report.false_positives)} false positive(s)[/] "
            "— said apply, was not worth it. [dim]Costs a day.[/]"
        )
        for result in report.false_positives:
            console.print(f"    [red]·[/] {result.case.id} — {result.case.why}")

    if report.separation is not None:
        console.print(
            f"\n  mean score {report.mean_score_worth:.0f} on the cases worth "
            f"applying to against {report.mean_score_not_worth:.0f} on those "
            f"that were not — [bold]{report.separation:+.0f} points[/] of "
            "separation"
        )

    if report.outcome_correlation is not None:
        console.print(
            f"\n[dim]Secondary: rank correlation between score and how far the "
            f"application got is {report.outcome_correlation:+.2f}. Reported "
            f"because it is the obvious measure, but it grades the scorer on "
            f"predicting the employer rather than on advising Alan — the Easy "
            f"Signs case scores badly here and is right.[/]"
        )

    if report.overrides:
        settled = [
            result for result in report.overrides
            if result.case.worth_applying is not Worth.unsure
        ]
        console.print(
            f"\n[bold]Overrides[/] — you generated against a skip "
            f"[bold]{len(report.overrides)}[/] time(s)"
        )
        if settled:
            console.print(
                f"  of the {len(settled)} since settled, you were right "
                f"[bold]{report.overrides_vindicated}[/] time(s)"
            )
            console.print(
                "  [dim]This is the standing disagreement settling on evidence. "
                "A run of overrides you were right about is the case for "
                "loosening the verdict threshold; a run you were wrong about is "
                "the case for leaving it alone.[/]"
            )
        else:
            console.print("  [dim]none of them have an outcome yet.[/]")

    notes = []
    if report.unlabelled:
        notes.append(f"{report.unlabelled} case(s) unlabelled")
    if report.unscored:
        notes.append(f"{report.unscored} unscored")
    if report.derived_labels:
        notes.append(
            f"{report.derived_labels} label(s) derived from outcomes.yaml notes "
            "rather than stated by Alan"
        )
    if notes:
        console.print(f"\n[dim]{'; '.join(notes)}.[/]")


def _render_cases(report: EvalReport) -> None:
    table = Table(box=None, pad_edge=False)
    table.add_column("case", style="cyan")
    table.add_column("verdict")
    table.add_column("score", justify="right")
    table.add_column("screen", justify="right")
    table.add_column("worth")
    table.add_column("outcome", style="dim")
    table.add_column("")
    table.add_column("model", style="dim")

    for result in report.results:
        assessment = result.assessment
        verdict = (
            f"[{_VERDICT_STYLE[assessment.verdict]}]{assessment.verdict.value}[/]"
            if assessment
            else "[dim]—[/]"
        )
        worth = result.case.worth_applying.value
        if result.case.label_derived and worth != Worth.unsure.value:
            worth += "*"
        agreement = result.agreement
        table.add_row(
            result.case.id,
            verdict,
            str(assessment.overall_score) if assessment else "—",
            str(assessment.recruiter_screen_score) if assessment else "—",
            worth,
            result.case.outcome.value,
            f"[{_AGREEMENT_STYLE[agreement]}]{agreement}[/]",
            (assessment.model_used or "—") if assessment else "—",
        )
    console.print(table)


def _delta(value: int) -> str:
    if value == 0:
        return "[dim]0[/]"
    colour = "green" if value > 0 else "red"
    return f"[{colour}]{value:+d}[/]"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def _load(
    cases_path: Path | None, *, model: str | None = None
) -> tuple[list[EvalCase], list[CaseResult]]:
    """Build the case set, from the pipeline unless a file was named.

    The store is the source: recording an outcome with `jobagent outcome` is
    how a case enters the eval set, so the set cannot go stale through neglect.
    `--cases` reads a file instead, which is how a snapshot is replayed.
    """
    try:
        with store.open_store(get_config().db_path) as conn:
            if cases_path is not None:
                cases = load_cases(cases_path)
            else:
                titles = {jd.id: jd.title for jd in store.list_jds(conn) if jd.id}
                cases = cases_from_applications(store.list_applications(conn), titles)
            results = [
                CaseResult(
                    case=case,
                    assessment=store.latest_assessment(conn, case.jd_id, model=model),
                )
                for case in cases
            ]
    except EvalError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)
    except StoreError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=1)

    if not cases:
        err_console.print(
            "[bold yellow]No finished applications to grade.[/] "
            "Record outcomes with `jobagent outcome <jd_id> <status> --worth ...`, "
            "or replay a snapshot with --cases."
        )
        raise typer.Exit(code=1)
    return cases, results
