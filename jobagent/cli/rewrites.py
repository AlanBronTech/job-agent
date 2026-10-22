"""`jobagent rewrites` — which checks send documents back to be written again. Free."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from jobagent.config import get_config
from jobagent.services import rewrites as rewrites_service
from jobagent.services.workspace import Workspace

console = Console()


def rewrites() -> None:
    """Which checks reject first drafts, and so double the time and cost of a generate."""
    r = rewrites_service.report(Workspace.from_config(get_config()))
    if not r.documents:
        console.print(
            "[dim]No records yet. They are kept from 2026-10-22 on, one per document "
            "per generate or revise.[/]"
        )
        return
    console.print(
        f"{r.rewritten} of {r.documents} document run(s) needed a rewrite "
        f"({', '.join(f'{d}: {n}' for d, n in r.by_document.most_common()) or 'none'})."
    )
    table = Table(box=None, pad_edge=False)
    table.add_column("rule")
    table.add_column("first drafts", justify="right")
    table.add_column("any draft", justify="right")
    table.add_column("still blocking", justify="right")
    table.add_column("example", style="dim")
    for rule, count in r.any_draft_rules.most_common():
        table.add_row(
            rule, str(r.first_draft_rules.get(rule, 0)), str(count),
            str(r.still_blocked.get(rule, 0)) or "", escape(r.examples.get(rule, "")[:70]),
        )
    console.print(table)
