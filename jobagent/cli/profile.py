"""`jobagent profile ...` commands. Thin: resolve config, call core, render."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from jobagent.config import get_config
from jobagent.core.profile import ProfileError, load_profile, summarize_profile

app = typer.Typer(help="Inspect and validate the profile.", no_args_is_help=True)

console = Console()
err_console = Console(stderr=True)


@app.command()
def validate(
    dir: Path | None = typer.Option(
        None,
        "--dir",
        "-d",
        help="Profile directory to validate (defaults to PROFILE_DIR).",
    ),
) -> None:
    """Validate the profile and print a summary. Exits non-zero on any error."""
    profile_dir = dir or get_config().profile_dir
    if profile_dir is None:
        err_console.print(
            "[bold red]No profile directory.[/] "
            "Set PROFILE_DIR in .env, or pass --dir."
        )
        raise typer.Exit(code=2)

    try:
        profile = load_profile(profile_dir)
    except ProfileError as exc:
        err_console.print(f"[bold red]Profile invalid[/] ({profile_dir})")
        err_console.print(str(exc))
        raise typer.Exit(code=1)

    summary = summarize_profile(profile)

    console.print(
        f"[bold green]Profile OK[/]  "
        f"[dim]{profile.roles.person.name} · {profile_dir}[/]"
    )
    _print_table("Sections", summary.section_counts)
    _print_table("Visibility", summary.visibility_breakdown)
    _print_table("Evidence strength", summary.evidence_breakdown)


def _print_table(title: str, counts: dict[str, int]) -> None:
    table = Table(title=title, title_justify="left", show_header=False, box=None)
    table.add_column(style="cyan")
    table.add_column(justify="right", style="bold")
    for key, value in counts.items():
        table.add_row(key, str(value))
    console.print(table)
