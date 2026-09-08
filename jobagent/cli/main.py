"""Top-level `jobagent` CLI. Subcommand groups mount here; no logic lives here."""

from __future__ import annotations

import os

import typer

from jobagent.adapters.prices import PRICES_FILE, unpriced_models
from jobagent.cli import apply as apply_cli
from jobagent.cli import config as config_cli
from jobagent.cli import evals as evals_cli
from jobagent.cli import generate as generate_cli
from jobagent.cli import jd as jd_cli
from jobagent.cli import prep as prep_cli
from jobagent.cli import profile as profile_cli
from jobagent.cli import score as score_cli
from jobagent.config import get_config


def report_unpriced_models(result: object = None, budget: bool = False) -> None:
    """Say so, once, if anything this run had no price for.

    A model missing from the price table costs real money and logs
    `cost_usd: null`. Left silent that reads as a free call and the spend
    figures quietly stop counting, which is exactly what happened when a Gemini
    model was routed to and nothing anywhere mentioned it.

    Registered as Typer's result callback so it runs once after the subcommand
    rather than once per model call — `generate` builds more than one client.
    """
    models = unpriced_models()
    if not models:
        return
    typer.secho(
        f"Note: no price for {', '.join(models)}. Those calls are logged with "
        f"price_unknown and are missing from any spend total. Add them to "
        f"{PRICES_FILE.name} (and update checked_on).",
        err=True,
        fg=typer.colors.YELLOW,
    )


app = typer.Typer(
    help="Personal, interactive job-application agent.",
    no_args_is_help=True,
    result_callback=report_unpriced_models,
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
app.command(name="apply")(apply_cli.apply)
app.command(name="outcome")(apply_cli.outcome)
app.command(name="status")(apply_cli.status_command)


if __name__ == "__main__":
    app()
