"""Spec 005: the agency resume, a longer PROFILE written for one ad.

Invented data only (Constitution VI): the example profile's person, and
invented employers and agencies.
"""

from __future__ import annotations

from jobagent.core.generate import SHORT_PROFILE_RULE, profile_rule
from jobagent.core.models import ResumeKind
from jobagent.core.prompts import load_prompt


def test_resume_kinds():
    assert ResumeKind.master.uses_master and not ResumeKind.master.long_profile
    assert ResumeKind.master_profile.uses_master and ResumeKind.master_profile.long_profile
    assert not ResumeKind.custom.uses_master and not ResumeKind.custom.long_profile
    assert ResumeKind.custom_profile.long_profile and not ResumeKind.custom_profile.uses_master
    assert not ResumeKind.master.generated
    assert all(k.generated for k in ResumeKind if k is not ResumeKind.master)


def test_profile_rule_default_is_the_short_rule():
    assert profile_rule(False) == SHORT_PROFILE_RULE
    assert SHORT_PROFILE_RULE.startswith("**PROFILE is two short paragraphs")


def test_profile_rule_long_is_the_shared_agency_rules():
    rule = profile_rule(True)
    assert rule == load_prompt("long_profile_rules").strip()
    assert "at most 250 words" in rule


def test_resume_prompt_has_one_profile_slot():
    text = (load_prompt.__globals__["PROMPTS_DIR"] / "generate_resume.md").read_text()
    assert text.count("{profile_rule}") == 1


# --------------------------------------------------------------------------- #
# T007: a copy of the master with only PROFILE replaced
# --------------------------------------------------------------------------- #

import hashlib
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Pt, RGBColor

from jobagent.adapters.docx_writer import DocxError, replace_profile


def build_master(path: Path, *, profile_heading: str | None = "PROFILE", body: int = 2,
                 twice: bool = False) -> Path:
    """An invented master in the masters' shape: plain paragraphs, run formatting."""
    doc = Document()

    def para(text, *, size=10.5, bold=False, colour=None, style=None):
        p = doc.add_paragraph(style=style)
        run = p.add_run(text)
        run.font.size = Pt(size)
        run.bold = bold
        if colour:
            run.font.color.rgb = colour
        return p

    para("SAM RIVERA", size=26, bold=True)
    para("Engineering Manager  ·  Platform", colour=RGBColor(0x22, 0x58, 0xA5))
    para("Melbourne  ·  sam@example.com", size=9.5)
    for _ in range(2 if twice else 1):
        if profile_heading:
            para(profile_heading, size=11.5, bold=True)
        for n in range(body):
            para(f"Master profile paragraph {n + 1}.", colour=RGBColor(0x10, 0x20, 0x30))
    para("CAREER HIGHLIGHTS", size=11.5, bold=True)
    para("Delivery: Shipped a freight tracker for Northwind Freight.", style="List Bullet")
    para("EXPERIENCE", size=11.5, bold=True)
    para("Engineering Manager  ·  Northwind Freight\t2022 – Present", bold=True)
    para("Led eight engineers.", style="List Bullet")
    doc.save(str(path))
    return path


def texts(path: Path) -> list[str]:
    return [p.text for p in Document(str(path)).paragraphs]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_replace_profile_changes_only_profile(tmp_path):
    master = build_master(tmp_path / "master.docx")
    before = digest(master)
    out = replace_profile(master, tmp_path / "out" / "copy.docx", ["One.", "Two.", "Three."])
    assert digest(master) == before  # the master is never written
    old, new = texts(master), texts(out)
    i = old.index("PROFILE")
    assert new[: i + 1] == old[: i + 1]
    assert new[i + 1 : i + 4] == ["One.", "Two.", "Three."]
    assert new[i + 4 :] == old[i + 3 :]


def test_replace_profile_keeps_the_master_paragraph_format(tmp_path):
    master = build_master(tmp_path / "master.docx")
    out = replace_profile(master, tmp_path / "copy.docx", ["One.", "Two.", "Three."])
    paras = Document(str(out)).paragraphs
    i = [p.text for p in paras].index("PROFILE")
    for p in paras[i + 1 : i + 4]:
        assert len(p.runs) == 1
        assert p.runs[0].font.size == Pt(10.5)
        assert p.runs[0].font.color.rgb == RGBColor(0x10, 0x20, 0x30)
        assert not p.runs[0].bold


@pytest.mark.parametrize("kwargs, words", [
    ({"profile_heading": None}, "no PROFILE"),
    ({"twice": True}, "more than one"),
    ({"body": 0}, "no paragraph"),
])
def test_replace_profile_refuses_what_it_cannot_place(tmp_path, kwargs, words):
    master = build_master(tmp_path / "master.docx", **kwargs)
    with pytest.raises(DocxError) as exc:
        replace_profile(master, tmp_path / "copy.docx", ["One."])
    assert "master.docx" in str(exc.value) and words in str(exc.value)
    assert not (tmp_path / "copy.docx").exists()


def test_master_on_page_reads_highlights_and_bullets(tmp_path):
    from jobagent.services.masters import master_on_page

    on_page = master_on_page(build_master(tmp_path / "master.docx"))
    assert on_page == {
        "master highlight 1": "Delivery: Shipped a freight tracker for Northwind Freight.",
        "master bullet 1": "Led eight engineers.",
    }
    assert master_on_page(tmp_path / "missing.docx") == {}
