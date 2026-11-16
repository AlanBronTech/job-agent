"""Formatting tests for the .docx renderer.

Every figure asserted here was measured off
`~/Documents/AlanBronMasterResume112026.docx`. The master is the source of
truth: if it and these tests disagree, the master wins and these change.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from jobagent.adapters.docx_writer import (
    CoverLetterContent,
    ResumeContent,
    RoleBlock,
    SkillCategory,
    write_cover_letter,
    write_resume,
)


def make_content(**overrides) -> ResumeContent:
    data = {
        "name": "ALAN BRON",
        "tagline": "Engineering Leader  ·  Co-Founder  ·  AI Adoption",
        "contact": "Sydney, NSW   ·   0459 000 000   ·   someone@example.com",
        "profile_paragraphs": ["First paragraph.", "Second paragraph."],
        "highlights": [("AI in production", "Deployed agentic tooling to a team.")],
        "skills": [
            SkillCategory("AI & Automation", "Agent development, prompt engineering"),
            SkillCategory("Leadership", "Teams to 15, hiring end-to-end"),
            SkillCategory("Backend", "Java, Python"),
        ],
        "roles": [
            RoleBlock("Software Development Manager", "Easy Signs", "2025 – 2026",
                      ["Led 15 engineers across three product streams."]),
            RoleBlock("AI Engineer & Consultant", "Bron Consulting", "2026 – Present",
                      ["Built an agentic system."]),
        ],
        "earlier_career": ["MLC / NAB: superannuation platform upgrades."],
        "education": ["PRINCE2 Foundation (APM Group)"],
    }
    data.update(overrides)
    return ResumeContent(**data)


@pytest.fixture
def rendered(tmp_path: Path) -> Document:
    return Document(str(write_resume(make_content(), tmp_path / "resume.docx")))


def find(doc: Document, prefix: str):
    return next(p for p in doc.paragraphs if p.text.startswith(prefix))


def signature(para):
    run = para.runs[0]
    fmt = para.paragraph_format
    return (
        run.font.size.pt,
        bool(run.font.bold),
        str(run.font.color.rgb) if run.font.color and run.font.color.rgb else None,
        fmt.space_before.pt if fmt.space_before else None,
        fmt.space_after.pt if fmt.space_after else None,
        fmt.line_spacing,
    )


# --------------------------------------------------------------------------- #
# Typography, against the master's measurements
# --------------------------------------------------------------------------- #


def test_the_name_block(rendered) -> None:
    assert signature(find(rendered, "ALAN BRON")) == (26.0, True, "1B3A6B", None, 1.5, 1.1)


def test_the_tagline(rendered) -> None:
    assert signature(find(rendered, "Engineering Leader")) == (
        10.5, False, "2258A5", None, 2.0, 1.1,
    )


def test_the_contact_line(rendered) -> None:
    assert signature(find(rendered, "Sydney, NSW")) == (
        9.5, False, "595959", None, None, 1.1,
    )


def test_section_headings(rendered) -> None:
    for heading in ("PROFILE", "CAREER HIGHLIGHTS", "EXPERIENCE", "EARLIER CAREER"):
        assert signature(find(rendered, heading)) == (
            11.5, True, "1B3A6B", 11.5, 5.5, 1.1,
        ), heading


def test_a_role_heading_carries_three_sizes_and_a_right_tab(rendered) -> None:
    """`Title  ·  Company` with the dates right-aligned at 16.93cm."""
    para = find(rendered, "Software Development Manager")
    sizes = [(run.text, run.font.size.pt, bool(run.font.bold)) for run in para.runs]

    assert sizes[0] == ("Software Development Manager", 11.5, True)
    assert sizes[2] == ("Easy Signs", 10.5, True)
    assert sizes[3] == ("\t2025 – 2026", 9.5, False)
    tabs = para.paragraph_format.tab_stops
    assert round(tabs[0].position.cm, 2) == 16.93


def test_headings_stay_with_what_follows_them(rendered) -> None:
    """A heading alone at the foot of a page, its bullet overleaf, reads as a mistake."""
    for heading in ("EXPERIENCE", "EARLIER CAREER", "Software Development Manager"):
        assert find(rendered, heading).paragraph_format.keep_with_next is True, heading


def test_bullets_use_the_template_numbering(rendered) -> None:
    para = find(rendered, "Led 15 engineers")

    assert "numPr" in para._p.xml
    assert para.style.name == "List Paragraph"
    assert signature(para)[3:] == (1.5, 3.6, 1.1)


def test_a_highlight_bullet_has_a_bold_label_then_a_colon(rendered) -> None:
    """The v4 master (2026-11-14): "**Delivery:** In each new lead role…". No em-dash."""
    para = find(rendered, "AI in production")

    assert para.runs[0].text == "AI in production: "
    assert para.runs[0].font.bold is True
    assert para.runs[1].font.bold is False


def test_the_page_setup_comes_from_the_template(rendered) -> None:
    section = rendered.sections[0]

    assert round(section.left_margin.cm, 2) == 1.68
    assert round(section.right_margin.cm, 2) == 1.68
    assert round(section.top_margin.cm, 2) == 1.32
    assert round(section.bottom_margin.cm, 2) == 1.23


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def test_sections_appear_in_the_specified_order(rendered) -> None:
    headings = [
        p.text for p in rendered.paragraphs
        if p.text.isupper() and p.text not in {"ALAN BRON"} and len(p.text) > 4
    ]

    assert headings == [
        "PROFILE",
        "CAREER HIGHLIGHTS",
        "CORE SKILLS",
        "EXPERIENCE",
        "EARLIER CAREER",
        "EDUCATION & CERTIFICATIONS",
    ]


def test_skills_render_as_one_labelled_line_each(rendered) -> None:
    """Measured from the v4 master: Normal, 10.5pt, 1pt before / 2pt after,
    a bold "Label: " run, then the list. No table."""
    assert rendered.tables == []
    para = find(rendered, "Leadership: ")
    # The template has no Normal style (see docx_writer); what matters is no bullet.
    assert para.style is None or para.style.name != "List Paragraph"
    assert para.runs[0].text == "Leadership: " and para.runs[0].font.bold is True
    assert para.runs[1].text == "Teams to 15, hiring end-to-end" and not para.runs[1].font.bold
    assert signature(para)[:5] == (10.5, True, None, 1.0, 2.0)
    labels = [p.text.split(":")[0] for p in rendered.paragraphs
              if p.runs and p.runs[0].text.endswith(": ")
              and (p.style is None or p.style.name != "List Paragraph")]
    assert labels == ["AI & Automation", "Leadership", "Backend"]


def test_an_earlier_career_line_bolds_the_name_before_the_colon(rendered) -> None:
    para = find(rendered, "MLC / NAB")
    assert para.runs[0].text == "MLC / NAB" and para.runs[0].font.bold is True
    assert para.runs[1].text == ": superannuation platform upgrades."


def test_no_em_dash_is_added_by_the_renderer(rendered) -> None:
    assert not any("\u2014" in p.text for p in rendered.paragraphs)


def test_an_empty_section_is_omitted_entirely(tmp_path: Path) -> None:
    path = write_resume(
        make_content(highlights=[], earlier_career=[], skills=[]),
        tmp_path / "sparse.docx",
    )
    text = "\n".join(p.text for p in Document(str(path)).paragraphs)

    assert "CAREER HIGHLIGHTS" not in text
    assert "EARLIER CAREER" not in text
    assert "CORE SKILLS" not in text
    assert "EXPERIENCE" in text


# --------------------------------------------------------------------------- #
# Cover letter
# --------------------------------------------------------------------------- #


def test_a_cover_letter_renders_its_parts(tmp_path: Path) -> None:
    path = write_cover_letter(
        CoverLetterContent(
            name="Alan Bron",
            contact="Sydney, NSW   ·   someone@example.com",
            date="1 September 2026",
            recipient=["Toshiba Global Commerce Solutions"],
            paragraphs=["First paragraph.", "Second paragraph."],
        ),
        tmp_path / "letter.docx",
    )
    text = [p.text for p in Document(str(path)).paragraphs if p.text.strip()]

    assert text[0] == "ALAN BRON" or text[0] == "Alan Bron"
    assert "1 September 2026" in text
    assert "Toshiba Global Commerce Solutions" in text
    assert "Dear Hiring Manager," in text
    assert "First paragraph." in text
    assert text[-2:] == ["Sincerely,", "Alan Bron"]


def test_a_cover_letter_renders_bullets_and_the_postscript(tmp_path: Path) -> None:
    """Alan's own letters list what he brings as bullets, then the citizenship line."""
    path = write_cover_letter(
        CoverLetterContent(
            name="Alan Bron",
            contact="Sydney, NSW",
            date="1 September 2026",
            paragraphs=["To summarise, my skills include:", "- Led a team of eight.", "- Shipped weekly."],
            postscript=["I have dual citizenship."],
        ),
        tmp_path / "letter.docx",
    )
    paragraphs = [p for p in Document(str(path)).paragraphs if p.text.strip()]
    bullets = [p.text for p in paragraphs if p._p.pPr is not None and p._p.pPr.numPr is not None]
    assert bullets == ["Led a team of eight.", "Shipped weekly."]
    texts = [p.text for p in paragraphs]
    assert texts.index("I have dual citizenship.") == texts.index("Sincerely,") - 1
