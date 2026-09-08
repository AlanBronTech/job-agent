"""`jobagent spend` — where the API bill went. Free; reads the run log.

The README quoted a per-application figure that came from adding up the
command estimates. This reports what was actually charged, from the log.
"""

from __future__ import annotations

from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.table import Table

from jobagent.adapters.prices import load_prices
from jobagent.config import get_config
from jobagent.core import store
from jobagent.core.spend import SpendGroup, SpendError, build_report, load_runs
from jobagent.core.store import StoreError

console = Console()
err_console = Console(stderr=True)

# Beyond this a breakdown stops being a summary. The tail is almost always
# single-cent rows, and `--jd` answers the question that made someone look.
_MAX_ROWS = 12


def spend(
    jd: int | None = typer.Option(None, "--jd", help="Only this job description."),
    model: str | None = typer.Option(
        None, "--model", help="Only calls to models matching this string."
    ),
    source: str | None = typer.Option(
        None, "--source", help="Only `cli` (real work) or `eval` (grading runs)."
    ),
    since: str | None = typer.Option(
        None, "--since", help="Only calls on or after this date (YYYY-MM-DD)."
    ),
) -> None:
    """Report API spend from the run log. Costs nothing to run."""
    config = get_config()

    cutoff = None
    if since is not None:
        try:
            cutoff = (
                datetime.strptime(since, "%Y-%m-%d")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        except ValueError:
            err_console.print(f"[bold red]--since wants YYYY-MM-DD, got {since!r}.[/]")
            raise typer.Exit(code=2)

    try:
        records = load_runs(config.runs_log_path)
    except SpendError as exc:
        err_console.print(f"[bold red]{exc}[/]")
        raise typer.Exit(code=2)

    report = build_report(
        records,
        model=model,
        source=source,
        jd_id=jd,
        since=cutoff,
        price_lookup=load_prices().lookup,
    )

    if not report.calls:
        console.print("[dim]No calls match.[/]")
        return

    _render_header(report)
    titles = _jd_titles(config)
    console.print()
    _render_table("By job description", report.by_jd, titles)
    _render_table("By call", report.by_label)
    _render_table("By command", report.by_command)
    if len(report.by_source) > 1:
        _render_table("Real work vs grading", report.by_source)


def _render_header(report) -> None:
    span = ""
    if report.first_ts and report.last_ts:
        first = datetime.fromtimestamp(report.first_ts).date()
        last = datetime.fromtimestamp(report.last_ts).date()
        span = f" between {first} and {last}" if first != last else f" on {first}"

    console.print(
        f"[bold]${report.total_usd:.2f}[/] over {report.calls} call(s){span}."
    )

    # CLAUDE.md: anything that reads a run history has to say which model it
    # read. Prices differ fivefold, so a mixed total is not one number.
    models = ", ".join(report.models)
    if report.mixed_models:
        console.print(f"[yellow]Mixed models: {models}.[/] Totals span both rates.")
    else:
        console.print(f"[dim]Model: {models}.[/]")

    gap = report.repricing_gap
    if gap is not None and abs(gap) > 0.01:
        console.print(
            f"[yellow]At today's prices the same calls cost "
            f"${report.repriced_usd:.2f}, {abs(gap):.0%} "
            f"{'less' if gap > 0 else 'more'}.[/] The log records what each "
            f"call was costed at when it ran; the difference is a price table "
            f"that has since changed or been corrected."
        )

    if report.unpriced_calls:
        console.print(
            f"[yellow]{report.unpriced_calls} call(s) had no price and are "
            f"missing from the total.[/] Add the model to prices.yaml."
        )


def _render_table(
    heading: str, groups: tuple[SpendGroup, ...], titles: dict[str, str] | None = None
) -> None:
    if not groups:
        return

    table = Table(title=heading, title_justify="left", title_style="bold")
    table.add_column("")
    table.add_column("Calls", justify="right")
    table.add_column("Cost", justify="right")

    for group in groups[:_MAX_ROWS]:
        name = group.key
        if titles and group.key in titles:
            name = f"{group.key} — {titles[group.key]}"
        cost = f"${group.cost_usd:.2f}"
        if group.unpriced_calls:
            cost += f" +{group.unpriced_calls}?"
        table.add_row(name, str(group.calls), cost)

    if len(groups) > _MAX_ROWS:
        table.add_row(f"[dim]… and {len(groups) - _MAX_ROWS} more[/]", "", "")

    console.print(table)
    console.print()


def _jd_titles(config) -> dict[str, str]:
    """`JD 22` -> `Engineering Manager · Ebury`, best effort.

    A bare id is a poor row label when the question is "what did the Ebury
    application cost". The report itself does not need the store, so a failure
    to open it costs the titles and nothing else.
    """
    try:
        with store.open_store(config.db_path) as conn:
            return {
                f"JD {jd.id}": f"{jd.title}"
                + (f" · {jd.company}" if jd.company else "")
                for jd in store.list_jds(conn, limit=1000)
            }
    except (StoreError, OSError):
        return {}
