"""`jobagent config ...` commands.

Exists to answer one question before any billed call: is .env actually wired,
and which provider will each call type hit? Getting that wrong is cheap to do
and expensive to discover — see the stale-profile incident that prompted
anchoring env_file to the repo root.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from jobagent.adapters.llm import CallType, LLMError, Provider, resolve_route
from jobagent.config import get_config

app = typer.Typer(help="Inspect runtime configuration.", no_args_is_help=True)

console = Console()


# Real keys are long: Anthropic ~100+ chars, Gemini ~39. Anything shorter, or
# containing an ellipsis, is the placeholder from .env.example. Treating a
# placeholder as "present" is the exact false confidence this command exists to
# prevent, so presence alone is not enough.
_MIN_PLAUSIBLE_KEY_LENGTH = 20


def _is_usable(secret: str | None) -> bool:
    return bool(
        secret
        and "..." not in secret
        and "…" not in secret
        and len(secret) >= _MIN_PLAUSIBLE_KEY_LENGTH
    )


def _mask(secret: str | None) -> str:
    """Render a key as evidence it is set, never as the key itself."""
    if not secret:
        return "[red]not set[/]"
    if not _is_usable(secret):
        return (
            f"[red]placeholder[/] [dim]{secret[:12]} "
            f"({len(secret)} chars) — not a real key[/]"
        )
    return f"[green]set[/] [dim]{secret[:6]}…{secret[-4:]} ({len(secret)} chars)[/]"


@app.command()
def check() -> None:
    """Show which keys are present and how each call type routes."""
    config = get_config()

    console.print("[bold]Keys[/]")
    keys = Table(show_header=False, box=None, pad_edge=False)
    keys.add_column(style="cyan")
    keys.add_column()
    keys.add_row("ANTHROPIC_API_KEY", _mask(config.anthropic_api_key))
    keys.add_row("GEMINI_API_KEY", _mask(config.gemini_api_key))
    console.print(keys)

    if config.budget_mode:
        console.print(
            "\n[bold yellow]BUDGET MODE[/] — every call routes to "
            f"[bold]{config.budget_model}[/], overriding the routing below. "
            "[dim]Free tier; the answers are worse. Unset BUDGET_MODE, or drop "
            "--budget, to go back.[/]"
        )

    console.print("\n[bold]Routing[/] [dim](LLM_<CALLTYPE> → LLM_DEFAULT → legacy)[/]")
    routes = Table(show_header=True, box=None, pad_edge=False)
    routes.add_column("call type", style="cyan")
    routes.add_column("provider")
    routes.add_column("model")
    routes.add_column("key")

    unusable: list[str] = []
    for call_type in CallType:
        try:
            route = resolve_route(config, call_type)
        except LLMError as exc:
            routes.add_row(call_type.value, "[red]unresolved[/]", f"[dim]{exc}[/]", "")
            unusable.append(call_type.value)
            continue

        has_key = _is_usable(
            config.anthropic_api_key
            if route.provider is Provider.anthropic
            else config.gemini_api_key
        )
        if not has_key:
            unusable.append(call_type.value)
        routes.add_row(
            call_type.value,
            route.provider.value,
            route.model,
            "[green]ok[/]" if has_key else "[red]missing[/]",
        )
    console.print(routes)

    console.print("\n[bold]Paths[/]")
    paths = Table(show_header=False, box=None, pad_edge=False)
    paths.add_column(style="cyan")
    paths.add_column()
    paths.add_row("profile_dir", str(config.profile_dir or "[red]not set[/]"))
    paths.add_row("db_path", str(config.db_path))
    paths.add_row("runs_log_path", str(config.runs_log_path))
    paths.add_row("output_dir", str(config.output_dir))
    paths.add_row("jd_dir", str(config.jd_dir))
    console.print(paths)

    if unusable:
        console.print(
            f"\n[yellow]Not ready:[/] {', '.join(unusable)} — "
            "no model configured, or the provider's key is missing."
        )
    else:
        console.print("\n[green]All call types are routed and keyed.[/]")
