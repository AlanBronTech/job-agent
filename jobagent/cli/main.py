"""Top-level `jobagent` CLI. Subcommand groups mount here; no logic lives here."""

from __future__ import annotations

import os

import typer

from jobagent.cli import config as config_cli
from jobagent.cli import evals as evals_cli
from jobagent.cli import generate as generate_cli
from jobagent.cli import jd as jd_cli
from jobagent.cli import prep as prep_cli
from jobagent.cli import profile as profile_cli
from jobagent.cli import score as score_cli
from jobagent.config import get_config

app = typer.Typer(
    help="Personal, interactive job-application agent.",
    no_args_is_help=True,
)


@app.callback()
def main(
    budget: bool = typer.Option(
        False,
        "--budget",
        "-b",
        help="Route every model call to the free-tier model (BUDGET_MODEL).",
    ),
) -> None:
    """Set process-wide options before any subcommand runs."""
    if budget:
        # Set through the environment rather than by mutating the config
        # object: config is read from the environment in one place and cached,
        # so this keeps a single source of truth and makes `config check`
        # report the same thing the run will actually do.
        os.environ["BUDGET_MODE"] = "true"
        get_config.cache_clear()


app.add_typer(profile_cli.app, name="profile")
app.add_typer(config_cli.app, name="config")
app.add_typer(jd_cli.app, name="jd")
app.add_typer(evals_cli.app, name="eval")
# `score` is one command, not a group — mounted directly.
app.command(name="score")(score_cli.score)
app.command(name="generate")(generate_cli.generate)
app.command(name="prep")(prep_cli.prep)


if __name__ == "__main__":
    app()
