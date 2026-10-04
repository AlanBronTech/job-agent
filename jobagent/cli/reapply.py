"""What the CLI says when the six-month rule stops a paid command.

Shared by `score` and `generate`, so both word it the same way. The refusal
carries the facts; this decides the words (contracts/cli.md, spec 002).
"""

from __future__ import annotations

import typer
from rich.console import Console

from jobagent.services import reapply
from jobagent.services.refusals import PossiblySameJob, SameJobRecently


def overrule_if_asked(ws, jd_id: int, today, asked: bool) -> None:
    """Record an overrule for this ad, but only if the rule would stop it."""
    if not asked:
        return
    state = reapply.check(ws, jd_id, today)
    if isinstance(state, (reapply.SameJob, reapply.PossiblySame)):
        reapply.decide(ws, jd_id, "overrule", state.match.against)


def refuse(console: Console, refusal: SameJobRecently | PossiblySameJob, jd_id: int, command: str) -> None:
    """Explain the refusal, say what to type next, and exit 2."""
    m = refusal.match
    applied = f"{m.applied_on:%-d %B %Y}"
    what = f"{m.company}, {m.title}" if m.company else m.title
    if isinstance(refusal, SameJobRecently):
        how = {
            "requisition": f"requisition {m.requisition_id}",
            "url": "the same ad URL",
            "title": "your answer that it is the same job",
        }[m.reason]
        console.print(
            f"[bold yellow]Same job you applied for on {applied}[/] "
            f"({m.age_days} days ago; {what}; matched on {how})."
        )
        console.print(
            "[dim]The reapplication window is set in your profile. Nothing was spent. "
            "To go ahead anyway:[/]"
        )
        console.print(f"  jobagent {command} {jd_id} --overrule-reapply")
    else:
        numbers = (
            f"requisition {m.requisition_id} on the earlier one, none in this ad"
            if m.requisition_id
            else "no requisition number on either"
        )
        console.print(
            f"[bold yellow]Possibly the same job as your application of {applied}[/] "
            f"({m.age_days} days ago; {what}; {numbers}). Nothing was spent."
        )
        console.print(f"  jobagent jd same {jd_id} yes   [dim]# same job: the rule applies[/]")
        console.print(f"  jobagent jd same {jd_id} no    [dim]# different job: go ahead[/]")
    raise typer.Exit(code=2)
