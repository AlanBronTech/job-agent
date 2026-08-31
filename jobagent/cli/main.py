"""Top-level `jobagent` CLI. Subcommand groups mount here; no logic lives here."""

from __future__ import annotations

import typer

from jobagent.cli import config as config_cli
from jobagent.cli import jd as jd_cli
from jobagent.cli import profile as profile_cli

app = typer.Typer(
    help="Personal, interactive job-application agent.",
    no_args_is_help=True,
)

app.add_typer(profile_cli.app, name="profile")
app.add_typer(config_cli.app, name="config")
app.add_typer(jd_cli.app, name="jd")


if __name__ == "__main__":
    app()
