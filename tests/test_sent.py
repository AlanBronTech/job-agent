"""Sent documents and `diff`: what went out, kept beside what was generated.

REVIEW-2026-10-18 task 1. Every company and sentence here is invented.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.adapters.docs import DocsError
from jobagent.adapters.docx_reader import DocxReadError, read_sections
from jobagent.adapters.docx_writer import (
    CoverLetterContent,
    ResumeContent,
    RoleBlock,
    SkillCategory,
    write_cover_letter,
    write_resume,
)
from jobagent.cli import apply as apply_cli
from jobagent.cli import sent as sent_cli
from jobagent.cli.main import app
from jobagent.core import store
from jobagent.core.diff import Section, compare, sentences
from jobagent.core.models import DocumentKind
from jobagent.services import sent
from jobagent.services.refusals import NoGeneratedCopy, NothingSent, SentFileUnusable
from tests.ui_seed import TODAY, seed, workspace

NOW = datetime(2026, 9, 29, 14, 0, 0)
LATER = datetime(2026, 9, 29, 16, 30, 0)


def resume_content(**overrides) -> ResumeContent:
    data = dict(
        name="ALEX EXAMPLE",
        tagline="Engineering Leader  ·  Delivery",
        contact="Sydney   ·   alex@example.com",
        profile_paragraphs=["Leads teams that ship.", "Twelve engineers at the last role."],
        highlights=[("Delivery", "Shipped the billing rewrite on time.")],
        skills=[SkillCategory("Leadership", "Hiring, coaching"), SkillCategory("Backend", "Python, Go")],
        roles=[
            RoleBlock("Engineering Manager", "Fictional Pty Ltd", "2024 – 2026",
                      ["Ran three squads.", "Moved releases from monthly to weekly."]),
            RoleBlock("Team Lead", "Invented Co", "2021 – 2024", ["Led six engineers."]),
        ],
        earlier_career=["Imaginary Bank — payments platform."],
        education=["BSc — Nowhere University"],
    )
    data.update(overrides)
    return ResumeContent(**data)


def letter_content(paragraphs) -> CoverLetterContent:
    return CoverLetterContent(
        name="Alex Example", contact="Sydney", date="29 September 2026",
        recipient=["Acme"], paragraphs=paragraphs,
    )


@pytest.fixture
def ws(tmp_path):
    return workspace(tmp_path)


@pytest.fixture
def ids(ws):
    return seed(ws)


@pytest.fixture
def acme(ws, ids):
    with store.open_store(ws.db_path) as conn:
        return store.get_jd(conn, ids["acme"])


def generate_into(ws, jd, *, resume=None, letter=None, now=NOW):
    """What `generate` does on disk: the visible file, then the kept copy."""
    from jobagent.adapters import docs

    names = []
    if resume is not None:
        name = docs.document_name("Resume", jd, when=TODAY)
        write_resume(resume, ws.documents.path_for_write(jd, TODAY, name))
        ws.documents.keep_generated(jd, TODAY, name, now)
        names.append(name)
    if letter is not None:
        name = docs.document_name("CoverLetter", jd, when=TODAY)
        write_cover_letter(letter, ws.documents.path_for_write(jd, TODAY, name))
        ws.documents.keep_generated(jd, TODAY, name, now)
        names.append(name)
    return names


def visible(ws, jd, name) -> Path:
    return ws.documents.output_dir / ws.documents.folder_name(jd, TODAY) / name


# --------------------------------------------------------------------------- #
# core.diff
# --------------------------------------------------------------------------- #


def test_identical_documents_are_unchanged():
    doc = [Section("PROFILE", ["Leads teams. Ships things."])]
    result = compare(doc, [Section("PROFILE", ["Leads teams. Ships things."])])
    assert result.unchanged and result.kept_share == 1.0


def test_an_edited_sentence_is_changed_not_added_and_removed():
    result = compare(
        [Section("PROFILE", ["Leads teams that ship. Likes Go."])],
        [Section("PROFILE", ["Leads teams that ship weekly. Likes Go."])],
    )
    profile = result.sections[0]
    assert profile.changed == [("Leads teams that ship.", "Leads teams that ship weekly.")]
    assert profile.added == [] and profile.removed == []
    # "ship." became "ship": the one generated word that did not survive.
    assert profile.kept_share == 5 / 6


def test_a_rewritten_sentence_is_removed_and_added():
    result = compare(
        [Section("PROFILE", ["Leads teams that ship."])],
        [Section("PROFILE", ["Thirty years of quiet competence."])],
    )
    profile = result.sections[0]
    assert profile.removed == ["Leads teams that ship."]
    assert profile.added == ["Thirty years of quiet competence."]
    assert profile.kept_share == 0.0


def test_a_renamed_section_still_counts_its_words_as_kept_overall():
    """Per section it is gone and new; over the whole document nothing was lost."""
    result = compare(
        [Section("CAREER HIGHLIGHTS", ["Shipped it."])],
        [Section("KEY ACHIEVEMENTS", ["Shipped it."])],
    )
    assert [s.kept_share for s in result.sections] == [0.0, None]
    assert result.kept_share == 1.0 and not result.unchanged


def test_a_bullet_without_a_full_stop_is_one_sentence():
    assert sentences(["Ran three squads", "One. Two."]) == ["Ran three squads", "One.", "Two."]


# --------------------------------------------------------------------------- #
# adapters.docx_reader, against what docx_writer renders
# --------------------------------------------------------------------------- #


def test_a_rendered_resume_reads_back_into_its_sections(tmp_path):
    path = write_resume(resume_content(), tmp_path / "r.docx")
    sections = {s.name: s.paragraphs for s in read_sections(path, "resume")}
    assert list(sections) == [
        "TAGLINE",
        "PROFILE",
        "CAREER HIGHLIGHTS",
        "CORE SKILLS",
        "EXPERIENCE: Engineering Manager · Fictional Pty Ltd",
        "EXPERIENCE: Team Lead · Invented Co",
        "EARLIER CAREER",
        "EDUCATION & CERTIFICATIONS",
    ]
    assert sections["TAGLINE"] == ["Engineering Leader  ·  Delivery"]
    # The table is read, which `doc.paragraphs` alone would skip.
    assert sections["CORE SKILLS"] == ["LEADERSHIP", "Hiring, coaching", "BACKEND", "Python, Go"]
    assert sections["EXPERIENCE: Team Lead · Invented Co"] == ["Led six engineers."]


def test_a_corrected_date_does_not_orphan_the_role(tmp_path):
    before = write_resume(resume_content(), tmp_path / "a.docx")
    roles = resume_content().roles
    roles[1] = RoleBlock("Team Lead", "Invented Co", "2020 – 2024", ["Led six engineers."])
    after = write_resume(resume_content(roles=roles), tmp_path / "b.docx")
    assert compare(read_sections(before, "resume"), read_sections(after, "resume")).unchanged


def test_a_letter_is_its_body_only(tmp_path):
    path = write_cover_letter(letter_content(["First.", "Second."]), tmp_path / "l.docx")
    assert [s.paragraphs for s in read_sections(path, "cover_letter")] == [["First.", "Second."]]


def test_a_pdf_is_refused_with_the_reason(tmp_path):
    path = tmp_path / "r.pdf"
    path.write_bytes(b"%PDF-1.4")
    with pytest.raises(DocxReadError, match="not a .docx"):
        read_sections(path, "resume")


# --------------------------------------------------------------------------- #
# Kept copies
# --------------------------------------------------------------------------- #


def test_a_generated_copy_survives_the_visible_file_being_edited(ws, acme):
    (name,) = generate_into(ws, acme, resume=resume_content())
    copy = ws.documents.generated_copies(acme, ws.documents.folder_name(acme, TODAY), TODAY)
    assert copy == [f".generated/20260929T140000/{name}"]

    write_resume(resume_content(profile_paragraphs=["Edited."]), visible(ws, acme, name))

    kept = ws.documents.local_path(acme, ws.documents.folder_name(acme, TODAY), copy[0], TODAY)
    assert "Leads teams that ship." in [p for s in read_sections(kept, "resume") for p in s.paragraphs]


def test_a_kept_copy_is_never_replaced(ws, acme):
    (name,) = generate_into(ws, acme, resume=resume_content())
    with pytest.raises(DocsError, match="never replaced"):
        ws.documents.keep_generated(acme, TODAY, name, NOW)


def test_kept_copies_do_not_appear_as_documents(ws, acme):
    generate_into(ws, acme, resume=resume_content())
    current = ws.documents.list_for(acme, TODAY).current
    assert [f.name for f in current.files] == ["AlanBron_Resume_AcmeLogistics_202609.docx"]


def test_a_path_outside_the_folder_cannot_be_read(ws, acme):
    generate_into(ws, acme, resume=resume_content())
    folder = ws.documents.folder_name(acme, TODAY)
    with pytest.raises(FileNotFoundError):
        ws.documents.local_path(acme, folder, "../../jobagent.db", TODAY)


# --------------------------------------------------------------------------- #
# services.sent
# --------------------------------------------------------------------------- #


def record(ws, jd_id, **kw):
    return sent.record(ws, jd_id, sent_on=TODAY, today=TODAY, now=LATER, **kw)


def test_an_edited_resume_is_recorded_against_the_newest_generated_copy(ws, ids, acme, tmp_path):
    generate_into(ws, acme, resume=resume_content(), now=NOW)
    (name,) = generate_into(ws, acme, resume=resume_content(), now=LATER)
    edited = write_resume(resume_content(profile_paragraphs=["Edited."]), tmp_path / name)

    (row,) = record(ws, ids["acme"], resume=edited)

    assert row.kind is DocumentKind.resume
    assert row.name == f"sent/2026-09-29/{name}"
    assert row.generated == f".generated/20260929T163000/{name}"
    assert not row.as_generated


def test_the_unedited_file_is_recognised_without_being_told(ws, ids, acme):
    (name,) = generate_into(ws, acme, resume=resume_content())
    (row,) = record(ws, ids["acme"], resume=visible(ws, acme, name))
    assert row.as_generated


def test_as_generated_records_both_kept_copies(ws, ids, acme):
    generate_into(ws, acme, resume=resume_content(), letter=letter_content(["One."]))
    rows = record(ws, ids["acme"], as_generated=True)
    assert [r.kind for r in rows] == [DocumentKind.resume, DocumentKind.cover_letter]
    assert all(r.as_generated and r.name.startswith("sent/2026-09-29/") for r in rows)


def test_as_generated_with_nothing_kept_is_refused_and_touches_nothing(ws, ids, acme):
    with pytest.raises(NoGeneratedCopy):
        record(ws, ids["acme"], as_generated=True)
    assert ws.documents.list_for(acme, TODAY).all == []


def test_a_missing_file_is_refused_before_anything_is_copied(ws, ids, acme, tmp_path):
    (name,) = generate_into(ws, acme, resume=resume_content())
    with pytest.raises(SentFileUnusable):
        record(ws, ids["acme"], resume=visible(ws, acme, name), letter=tmp_path / "gone.docx")
    assert not (visible(ws, acme, "sent")).exists()
    assert sent.recorded(ws, ids["acme"]) == []


def test_recording_the_same_file_twice_adds_nothing(ws, ids, acme):
    (name,) = generate_into(ws, acme, resume=resume_content())
    first = record(ws, ids["acme"], resume=visible(ws, acme, name))
    second = record(ws, ids["acme"], resume=visible(ws, acme, name))
    assert [r.id for r in first] == [r.id for r in second]
    assert len(sent.recorded(ws, ids["acme"])) == 1


def test_an_old_folder_can_supply_its_generated_original(ws, ids, acme, tmp_path):
    """Before copies were kept: the v1 next to the v2 that was sent."""
    original = write_resume(resume_content(), tmp_path / "AlanBron_Resume_Acme_202609.docx")
    edited = write_resume(
        resume_content(profile_paragraphs=["Edited."]), tmp_path / "AlanBron_Resume_Acme_202609_v2.docx"
    )
    (row,) = record(ws, ids["acme"], resume=edited, generated_resume=original)
    assert row.generated == ".generated/recorded-20260929T163000/AlanBron_Resume_Acme_202609.docx"

    (comparison,) = sent.compare_sent(ws, ids["acme"], TODAY)
    assert comparison.problem is None
    profile = next(s for s in comparison.diff.sections if s.name == "PROFILE")
    assert profile.added == ["Edited."]


def test_a_sent_file_with_nothing_to_compare_says_so(ws, ids, tmp_path):
    letter = write_cover_letter(letter_content(["One."]), tmp_path / "AlanBron_CoverLetter_Acme_202609.docx")
    record(ws, ids["acme"], letter=letter)
    (comparison,) = sent.compare_sent(ws, ids["acme"], TODAY)
    assert comparison.diff is None and "no generated copy" in comparison.problem


def test_diff_with_nothing_sent_is_refused(ws, ids):
    with pytest.raises(NothingSent):
        sent.compare_sent(ws, ids["acme"], TODAY)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

runner = CliRunner()


@pytest.fixture
def wired(ws, monkeypatch):
    """Both commands build their workspace from config; hand them the test's."""
    monkeypatch.setattr(sent_cli.Workspace, "from_config", classmethod(lambda cls, config: ws))
    monkeypatch.setattr(sent_cli, "get_config", lambda: None)
    monkeypatch.setattr(apply_cli, "get_config", lambda: None)
    return ws


def test_apply_records_what_was_sent(wired, ids, acme, tmp_path, monkeypatch):
    (name,) = generate_into(wired, acme, resume=resume_content())
    edited = write_resume(resume_content(profile_paragraphs=["Edited."]), tmp_path / name)

    result = runner.invoke(app, ["apply", str(ids["acme"]), "--sent-resume", str(edited)])

    assert result.exit_code == 0, result.output
    assert "Resume: kept as" in result.output
    with store.open_store(wired.db_path) as conn:
        assert store.get_application(conn, ids["acme"]).status.value == "applied"
        assert len(store.list_sent(conn, ids["acme"])) == 1


def test_apply_with_a_bad_file_records_no_application(wired, ids, tmp_path):
    result = runner.invoke(
        app, ["apply", str(ids["acme"]), "--sent-resume", str(tmp_path / "gone.docx")]
    )
    assert result.exit_code == 2
    with store.open_store(wired.db_path) as conn:
        assert store.get_application(conn, ids["acme"]) is None


def test_diff_prints_kept_share_and_the_changed_sentence(wired, ids, acme, tmp_path):
    (name,) = generate_into(wired, acme, resume=resume_content())
    edited = write_resume(
        resume_content(profile_paragraphs=["Leads teams that ship weekly.", "Twelve engineers at the last role."]),
        tmp_path / name,
    )
    record(wired, ids["acme"], resume=edited)

    result = runner.invoke(app, ["diff", str(ids["acme"])])

    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "of generated words kept" in out
    assert "~ Leads teams that ship. → Leads teams that ship weekly." in out


def test_diff_all_counts_the_unedited(wired, ids, acme):
    generate_into(wired, acme, resume=resume_content(), letter=letter_content(["One."]))
    record(wired, ids["acme"], as_generated=True)

    result = runner.invoke(app, ["diff", "--all"])

    assert result.exit_code == 0, result.output
    assert "2 of 2 document(s) sent unedited." in result.output


def test_diff_of_two_files_needs_no_records(wired, tmp_path):
    a = write_resume(resume_content(), tmp_path / "AlanBron_Resume_X_202609.docx")
    b = write_resume(resume_content(), tmp_path / "AlanBron_Resume_X_202609_v2.docx")
    result = runner.invoke(app, ["diff", "--generated", str(a), "--sent", str(b)])
    assert result.exit_code == 0, result.output
    assert "Sent exactly as generated." in result.output


def test_sent_records_follow_a_superseded_folder(ws, ids, acme):
    (name,) = generate_into(ws, acme, resume=resume_content())
    record(ws, ids["acme"], resume=visible(ws, acme, name))
    moved = ws.documents.supersede(acme, TODAY, LATER)
    with store.open_store(ws.db_path) as conn:
        store.move_sent_folder(conn, ws.documents.folder_name(acme, TODAY), moved)
    (comparison,) = sent.compare_sent(ws, ids["acme"], TODAY)
    assert comparison.sent.folder == moved and comparison.diff.unchanged
