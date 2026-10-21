"""Revising a document through the tool, and the context given to every writer.

REVIEW-2026-10-18 task 2. The model is replaced by fakes that record what
they were asked; every company and sentence is invented.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from jobagent.adapters.docx_writer import write_resume
from jobagent.adapters.llm import RunContext
from jobagent.cli import revise as revise_cli
from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core import notes as core_notes
from jobagent.core import store
from jobagent.core.generate import instructions_block
from jobagent.core.models import DocumentKind, RevisionNote
from jobagent.services import documents, revise
from jobagent.services.refusals import EditedByHand, NoGeneratedCopy
from jobagent.services.workspace import Workspace
from tests.test_sent import resume_content
from tests.ui_seed import TODAY, seed, workspace

EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
CONFIG = Config(_env_file=None, llm_default="anthropic:claude-sonnet-5")
FIRST = datetime(2026, 9, 29, 14, 0, 0)
SECOND = datetime(2026, 9, 29, 15, 0, 0)


@pytest.fixture
def ws(tmp_path):
    base = workspace(tmp_path)
    return Workspace(**{**base.__dict__, "profile_dir": EXAMPLE_PROFILE})


@pytest.fixture
def ids(ws):
    return seed(ws)


@pytest.fixture
def model(monkeypatch):
    """Builders that record the instructions they were given."""
    seen = []
    drafts = iter([["Leads teams that ship."], ["Leads teams that ship weekly."]] + [["Again."]] * 5)

    def build_resume(jd, profile, assessment, *, client, today, instructions=None, **_):
        seen.append(("resume", instructions))
        return SimpleNamespace(content=resume_content(profile_paragraphs=next(drafts)), issues=[], unused=[])

    def build_cover_letter(jd, profile, assessment, *, client, instructions=None, **_):
        seen.append(("cover", instructions))
        return SimpleNamespace(text="One.\n\nTwo.", issues=[])

    monkeypatch.setattr(documents, "get_client", lambda *a, **k: object())
    monkeypatch.setattr(documents.role_kind, "ensure", lambda *a, **k: None)
    monkeypatch.setattr(documents, "build_resume", build_resume)
    monkeypatch.setattr(documents, "build_cover_letter", build_cover_letter)
    return seen


def generate(ws, jd_id, **kw):
    options = dict(resume=True, cover=False, questions=[], today=TODAY, now=FIRST, check_claims=False)
    options.update(kw)
    return documents.generate(ws, CONFIG, RunContext(command="generate", jd_id=jd_id), jd_id, **options)


def run_revise(ws, jd_id, note="Say weekly.", **kw):
    options = dict(kind=DocumentKind.resume, note=note, today=TODAY, now=SECOND, check_claims=False)
    options.update(kw)
    return revise.revise(ws, CONFIG, RunContext(command="revise", jd_id=jd_id), jd_id, **options)


# -- the prompt text ------------------------------------------------------------


def test_nothing_to_add_is_no_block():
    assert instructions_block() is None


def test_the_revision_block_carries_the_draft_the_note_and_the_rule():
    block = " ".join(instructions_block(previous="PROFILE\nOld line.", note="Say weekly.", document="resume").split())
    assert "Old line." in block and "Say weekly." in block
    assert "never a route around the evidence" in block


def test_context_says_it_is_not_evidence():
    block = " ".join(instructions_block(context="Recruiter said payments matter most.").split())
    assert "Recruiter said payments matter most." in block and "not evidence about Alan" in block


# -- revise --------------------------------------------------------------------


def test_a_revision_gets_the_previous_draft_and_the_note(ws, ids, model):
    generate(ws, ids["acme"])
    result, note = run_revise(ws, ids["acme"])
    _, given = model[-1]
    assert "Leads teams that ship." in given and "Say weekly." in given
    assert note.id and note.result == f".generated/20260929T150000/{result.written[0].name}"
    # Both versions kept.
    copies = ws.documents.generated_copies(_jd(ws, ids), result.folder.name, TODAY)
    assert [c.split("/")[1] for c in copies] == ["20260929T150000", "20260929T140000"]


def _jd(ws, ids):
    with store.open_store(ws.db_path) as conn:
        return store.get_jd(conn, ids["acme"])


def test_a_hand_edited_file_is_refused_before_anything_is_spent(ws, ids, model):
    first = generate(ws, ids["acme"])
    write_resume(resume_content(profile_paragraphs=["Edited by hand."]), first.written[0])
    calls = len(model)
    with pytest.raises(EditedByHand):
        run_revise(ws, ids["acme"])
    assert len(model) == calls
    assert revise.notes(ws, ids["acme"]) == []


def test_replacing_edits_keeps_the_edited_file(ws, ids, model):
    first = generate(ws, ids["acme"])
    write_resume(resume_content(profile_paragraphs=["Edited by hand."]), first.written[0])
    run_revise(ws, ids["acme"], replace_edits=True)
    kept = first.folder / ".edited" / "20260929T150000" / first.written[0].name
    assert kept.is_file()


def test_nothing_generated_is_refused(ws, ids, model):
    with pytest.raises(NoGeneratedCopy):
        run_revise(ws, ids["acme"])


def test_an_empty_note_is_refused(ws, ids, model):
    generate(ws, ids["acme"])
    with pytest.raises(ValueError):
        run_revise(ws, ids["acme"], note="  ")


def test_a_not_ready_file_revised_clean_leaves_one_file(ws, ids, model, monkeypatch):
    from jobagent.core.validation import Severity, ValidationIssue

    blocker = ValidationIssue(rule="x", severity=Severity.blocker, detail="bad")
    original = documents.build_resume
    monkeypatch.setattr(documents, "build_resume", lambda *a, **k: SimpleNamespace(
        content=resume_content(), issues=[blocker], unused=[]))
    first = generate(ws, ids["acme"])
    assert first.written[0].name.endswith("_NOT-READY.docx")
    monkeypatch.setattr(documents, "build_resume", original)
    run_revise(ws, ids["acme"])
    docx = sorted(p.name for p in first.folder.iterdir() if p.suffix == ".docx")
    assert docx == ["AlanBron_Resume_AcmeLogistics_202609.docx"]


# -- context -------------------------------------------------------------------


def test_context_reaches_every_writer(ws, ids, model):
    revise.add_context(ws, ids["acme"], "Recruiter said payments matter most.", FIRST)
    generate(ws, ids["acme"], cover=True)
    assert all("payments matter most" in (given or "") for _, given in model)


def test_context_lines_append_and_clear(ws, ids):
    revise.add_context(ws, ids["acme"], "One.", FIRST)
    assert revise.add_context(ws, ids["acme"], "Two.", FIRST) == "One.\nTwo."
    revise.set_context(ws, ids["acme"], "", FIRST)
    assert revise.context(ws, ids["acme"]) is None


def test_context_never_reaches_the_ad_record(ws, ids):
    """The scorer and the eval read the ad; context was not part of it."""
    revise.add_context(ws, ids["acme"], "Recruiter said payments.", FIRST)
    jd = _jd(ws, ids)
    assert "payments" not in jd.model_dump_json()


# -- notes report --------------------------------------------------------------


def note(jd_id, text):
    return RevisionNote(jd_id=jd_id, kind=DocumentKind.cover_letter, note=text, created_at=FIRST)


def test_a_note_given_for_three_applications_is_recurring():
    groups = core_notes.group([
        note(1, "Drop the opener about passion for the mission"),
        note(2, "Shorter paragraphs please"),
        note(3, "drop the opener about the mission"),
        note(4, "Drop the mission opener"),
    ])
    assert groups[0].recurring and groups[0].applications == 3
    assert not groups[1].recurring


# -- CLI -----------------------------------------------------------------------

runner = CliRunner()


@pytest.fixture
def wired(ws, monkeypatch):
    monkeypatch.setattr(revise_cli.Workspace, "from_config", classmethod(lambda cls, c: ws))
    monkeypatch.setattr(revise_cli, "get_config", lambda: CONFIG)
    return ws


def test_revise_one_document_at_a_time(wired, ids):
    result = runner.invoke(app, ["revise", str(ids["acme"]), "--resume", "--cover", "--note", "x"])
    assert result.exit_code == 2 and "one document at a time" in result.output


def test_revise_refuses_an_edited_file_and_says_how_to_go_on(wired, ids, model):
    from datetime import date

    first = generate(wired, ids["acme"], today=date.today())
    write_resume(resume_content(profile_paragraphs=["Edited by hand."]), first.written[0])
    result = runner.invoke(app, ["revise", str(ids["acme"]), "--resume", "--note", "x"])
    out = " ".join(result.output.split())
    assert result.exit_code == 2 and "--replace-edits" in out and "Nothing was spent" in out


def test_context_command_adds_and_shows(wired, ids):
    runner.invoke(app, ["context", str(ids["acme"]), "Recruiter said payments."])
    result = runner.invoke(app, ["context", str(ids["acme"])])
    assert "Recruiter said payments." in result.output


def test_notes_command_flags_a_recurring_note(wired, ids):
    with store.open_store(wired.db_path) as conn:
        for jd_id in ids.values():
            store.add_revision_note(conn, note(jd_id, "Drop the mission opener"))
    result = runner.invoke(app, ["notes"])
    assert result.exit_code == 0 and "promote to voice.md" in result.output
