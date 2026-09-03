"""Rendering the pipeline's own record of a company. Shared by three commands.

Printed by `jd add`, `score` and `generate`, all before the expensive part.
It is deliberately a report and not a decision: the last line says so, because
a warning that looks like a verdict is one Alan has to argue with.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from jobagent.core.models import ApplicationStatus, CompanyHistory, PriorEncounter

# How far it got, in words. The enum values are for the database.
_STATUS_WORDS = {
    ApplicationStatus.identified: ("identified, not applied", "dim"),
    ApplicationStatus.applied: ("applied, waiting", "yellow"),
    ApplicationStatus.applied_no_reply: ("applied, no reply", "yellow"),
    ApplicationStatus.rejected_screen: ("rejected at screen", "red"),
    ApplicationStatus.recruiter_call: ("recruiter call", "green"),
    ApplicationStatus.interview_1: ("first interview", "green"),
    ApplicationStatus.interview_2: ("second interview", "green"),
    ApplicationStatus.offer: ("offer", "bold green"),
    ApplicationStatus.withdrew: ("withdrew", "dim"),
    ApplicationStatus.not_applied: ("not applied", "dim"),
}

# Enough to see the pattern without burying the ad just parsed. Nuix already
# has four rows and Care GP three, all re-ingests of one ad each.
_MAX_ROWS = 5

# Alan's own note on an application is the most useful line here — "I learned
# not to apply to Xero again" is worth more than any status word — but it is
# free text and some of it is a paragraph.
_MAX_NOTE = 160
# Below this a narrow terminal is cutting the note down to nothing, at which
# point it is better to overrun the width than to print an ellipsis.
_MIN_NOTE = 48


def render_company_history(console: Console, history: CompanyHistory) -> None:
    """Print what the store already holds for this company. Silent if nothing.

    Laid out by hand rather than with a ``Table``. Alan's own note on an
    application is the line worth reading, and a table sizes its columns to the
    longest title, which wrapped a one-sentence note over four lines.
    """
    if not history:
        return

    rows = history.encounters[:_MAX_ROWS]
    id_width = max(len(f"JD {row.jd_id}") for row in rows)
    title_width = max(len(row.title) for row in rows)
    indent = 2 + id_width + 2 + len("2026-09-01") + 2

    console.print()
    console.print(f"[bold yellow]Seen before — {history.company}[/]")

    for encounter in rows:
        words, style = _status(encounter)
        console.print(
            f"  [cyan]{f'JD {encounter.jd_id}':>{id_width}}[/]"
            f"  [dim]{encounter.ingested_at:%Y-%m-%d}[/]"
            f"  {encounter.title:<{title_width}}"
            f"  [{style}]{words}[/]"
        )
        note = _note(encounter, width=console.width - indent)
        if note:
            console.print(f"{' ' * indent}[dim]{note}[/]")

    hidden = len(history.encounters) - _MAX_ROWS
    if hidden > 0:
        console.print(f"  [dim]…and {hidden} earlier.[/]")

    console.print(f"  [dim]{_summary(history)}[/]")


def _status(encounter: PriorEncounter) -> tuple[str, str]:
    """How far it got, and how loudly to say so."""
    words, style = (
        _STATUS_WORDS[encounter.status]
        if encounter.status is not None
        else ("not applied", "dim")
    )
    if encounter.same_posting:
        words += " · the same posting"
    return words, style


def _note(encounter: PriorEncounter, *, width: int) -> str:
    """Alan's retrospective judgment, where he recorded one.

    Truncated to the space left on the line rather than wrapped: the second
    line of a wrapped note starts at column zero and reads as a new row.
    """
    if not encounter.worth_why:
        return ""
    verdict = (
        f"worth it: {encounter.worth_applying.value}. "
        if encounter.worth_applying is not None
        else ""
    )
    text = verdict + "“" + " ".join(encounter.worth_why.split()) + "”"
    limit = max(_MIN_NOTE, min(_MAX_NOTE, width))
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _summary(history: CompanyHistory) -> str:
    ads = len(history.encounters)
    parts = [f"{ads} earlier {'ad' if ads == 1 else 'ads'}"]

    applications = len(history.applications)
    if applications:
        parts.append(f"{applications} applied to")
    rejections = len(history.rejections)
    if rejections:
        parts.append(
            f"{rejections} rejected at screen"
            if rejections > 1
            else "1 rejected at screen"
        )
    duplicates = len(history.same_posting)
    if duplicates:
        parts.append(f"{duplicates} the same posting as this one")

    return ", ".join(parts) + ". This does not change the verdict."
