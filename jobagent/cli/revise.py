"""`jobagent revise`, `notes` and `context` — correcting documents through the
tool instead of by hand, so that every correction is kept and can be counted.

`revise` costs what generating that one document costs, plus the previous
draft in the prompt; `notes` and `context` are free.
"""

from __future__ import annotations

from datetime import date, datetime

import typer
from rich.console import Console
from rich.markup import escape

from jobagent.adapters.llm import RunContext
from jobagent.cli.estimate import print_estimate
from jobagent.cli.generate import _FAILED, _report, _report_readiness
from jobagent.config import get_config
from jobagent.core import notes as core_notes
from jobagent.core.models import DocumentKind
from jobagent.core.store import StoreError
from jobagent.services import revise as revise_service
from jobagent.services.documents import GenerationFailed
from jobagent.services.refusals import (
    EditedByHand,
    NoGeneratedCopy,
    NoModel,
    NoSuchAd,
    NotScored,
    ProfileInvalid,
    ProfileMissing,
    PossiblySameJob,
    SameJobRecently,
)
from jobagent.cli.reapply import refuse as refuse_reapply
from jobagent.services.workspace import Workspace

console = Console()
err_console = Console(stderr=True)


def revise(
    jd_id: int = typer.Argument(..., help="The JD id."),
    resume: bool = typer.Option(False, "--resume", help="Revise the resume."),
    cover: bool = typer.Option(False, "--cover", help="Revise the cover letter."),
    note: str = typer.Option(..., "--note", help="What to change, in your words. Kept."),
    replace_edits: bool = typer.Option(
        False, "--replace-edits",
        help="The file was edited by hand: keep that version under .edited/ and revise anyway.",
    ),
    no_check_claims: bool = typer.Option(
        False, "--no-check-claims", help="Skip the paid claim check of the letter."
    ),
) -> None:
    """Write a generated document again, changed as your note says."""
    if resume == cover:
        _refuse("Revise one document at a time: --resume or --cover.")
    kind = DocumentKind.resume if resume else DocumentKind.cover_letter
    config = get_config()
    ws = Workspace.from_config(config)
    check_claims = config.check_claims and not no_check_claims
    try:
        result, record = revise_service.revise(
            ws, config, RunContext(command="revise", jd_id=jd_id), jd_id,
            kind=kind, note=note, today=date.today(), now=datetime.now(),
            replace_edits=replace_edits, check_claims=check_claims,
            before_spend=lambda: print_estimate(
                config, "generate", resume=resume, cover=cover, answers=False,
                check_claims=check_claims, review=False, jd_id=jd_id,
            ),
        )
    except ValueError as exc:
        _refuse(str(exc))
    except (SameJobRecently, PossiblySameJob) as refusal:
        refuse_reapply(err_console, refusal, jd_id, "revise")
    except NoSuchAd:
        _refuse(f"No job description with id {jd_id}.", code=1)
    except NotScored:
        _refuse(f"JD {jd_id} has not been scored.")
    except NoGeneratedCopy as refusal:
        _refuse(
            f"No generated {refusal.kind} is kept in {refusal.folder}. Revise works on "
            "documents generated from 2026-10-21 on; generate it first."
        )
    except EditedByHand as refusal:
        _refuse(
            f"{refusal.name} has been edited since it was generated. A revision starts "
            "from the generated version, so those edits would not be in it. Say what they "
            "were in --note, or pass --replace-edits to keep the edited file under .edited/ "
            "and revise anyway. Nothing was spent."
        )
    except ProfileMissing:
        _refuse("No profile directory. Set PROFILE_DIR in .env.")
    except ProfileInvalid as refusal:
        _refuse(f"Profile invalid: {refusal.detail}", code=1)
    except NoModel as refusal:
        _refuse(f"No model available for generation. {refusal.detail}")
    except GenerationFailed as failure:
        _refuse(f"{_FAILED[failure.stage]} {failure.cause}", code=1)
    except StoreError as exc:
        _refuse(str(exc), code=1)

    for warning in result.warnings:
        err_console.print(f"[yellow]{escape(warning)}[/]")
    console.print(f"[dim]Note {record.id} kept. The previous version is in .generated/.[/]")
    _report(result.folder, result.written, result.issues, result.unused)
    _report_readiness(result)


def notes(
    jd_id: int | None = typer.Option(None, "--jd", help="One job's notes only."),
) -> None:
    """Revision notes, grouped: one given across three applications wants a rule."""
    ws = Workspace.from_config(get_config())
    try:
        found = revise_service.notes(ws, jd_id)
    except StoreError as exc:
        _refuse(str(exc), code=1)
    if not found:
        console.print("[dim]No revision notes yet. `jobagent revise ID --resume --note …`[/]")
        return
    for group in core_notes.group(found):
        head = (
            f"[bold yellow]{group.applications} applications[/] — promote to voice.md, a "
            "note_for_writer, or a profile fact?"
            if group.recurring
            else f"[dim]{group.applications} application(s)[/]"
        )
        console.print(f"\n{head}")
        for n in group.notes:
            label = "resume" if n.kind is DocumentKind.resume else "letter"
            console.print(f"  JD {n.jd_id:<4} {label:<6} {n.created_at:%Y-%m-%d}  {escape(n.note)}")


def context(
    jd_id: int = typer.Argument(..., help="The JD id."),
    add: str | None = typer.Argument(None, help="A line to add, e.g. what a recruiter said."),
    set_: str | None = typer.Option(None, "--set", help="Replace the context with this."),
    clear: bool = typer.Option(False, "--clear", help="Remove the context."),
) -> None:
    """What you know about an application that the ad does not say. Given to every writer."""
    ws = Workspace.from_config(get_config())
    now = datetime.now()
    try:
        if clear:
            revise_service.set_context(ws, jd_id, "", now)
        elif set_ is not None:
            revise_service.set_context(ws, jd_id, set_, now)
        elif add:
            revise_service.add_context(ws, jd_id, add, now)
        text = revise_service.context(ws, jd_id)
    except NoSuchAd:
        _refuse(f"No job description with id {jd_id}.", code=1)
    except StoreError as exc:
        _refuse(str(exc), code=1)
    if text:
        console.print(escape(text))
    else:
        console.print(f"[dim]No context for JD {jd_id}.[/]")


def _refuse(message: str, *, code: int = 2):
    err_console.print(f"[bold red]{escape(message)}[/]")
    raise typer.Exit(code=code)
