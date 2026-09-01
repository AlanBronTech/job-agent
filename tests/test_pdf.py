"""Unit tests for reading a job ad out of a printed job page.

The PDFs are built here rather than committed: Alan's real saved pages are
half a megabyte each and carry his LinkedIn session. Nothing in this path
touches the network — the adapter reads a file he already saved, by design and
by hard rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobagent.adapters.pdf import PDFError, extract_ad, looks_like_pdf

HEADER = "01/09/2026, 10:14   Engineering Manager | Acme | LinkedIn"


def _footer(page: int, of: int) -> str:
    return f"https://www.linkedin.com/jobs/view/4417048804/   {page}/{of}"


def write_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Write a minimal text-only PDF, one text line per source line.

    Hand-built because the project has no PDF *writer*, and adding one to draw
    four lines of Helvetica would be a dependency bought for the test suite
    alone. Each line is positioned absolutely so that layout-mode extraction —
    what the adapter uses — has real coordinates to reconstruct.
    """
    objects: dict[int, bytes] = {}
    font = 3
    first_page = 4
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(len(pages)))

    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[font] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )

    for index, lines in enumerate(pages):
        page_number = first_page + 2 * index
        content_number = page_number + 1
        objects[page_number] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font} 0 R >> >> "
            f"/Contents {content_number} 0 R >>"
        ).encode()

        operators = ["BT /F1 10 Tf"]
        y = 800
        for line in lines:
            escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            operators.append(f"1 0 0 1 60 {y} Tm ({escaped}) Tj")
            y -= 16
        operators.append("ET")
        # WinAnsi, to match the font declared above: the middle dot in a
        # posting line and the ellipsis in a "…more" toggle both matter here.
        stream = "\n".join(operators).encode("cp1252")
        objects[content_number] = (
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number + objects[number] + b"\nendobj\n"

    xref_at = len(out)
    size = max(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for number in range(1, size):
        out += b"%010d 00000 n \n" % offsets[number]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        size,
        xref_at,
    )

    path.write_bytes(bytes(out))
    return path


@pytest.fixture
def linkedin_pdf(tmp_path: Path) -> Path:
    return write_pdf(
        tmp_path / "ad.pdf",
        [
            [
                HEADER,
                "Acme Corp",
                "Engineering Manager",
                "Sydney, New South Wales, Australia·Reposted 2 weeks ago"
                "·72 people clicked apply",
                "Take the next step in your job search",
                "About the job",
                "You will lead two squads and own delivery.",
                _footer(1, 2),
            ],
            [
                HEADER,
                "Required: PHP and React",
                "Set alert for similar jobs",
                "People also viewed",
                "Some other role at Another Company",
                _footer(2, 2),
            ],
        ],
    )


def test_recognises_a_pdf_by_suffix(tmp_path: Path) -> None:
    assert looks_like_pdf(tmp_path / "whatever.PDF")


def test_recognises_a_pdf_by_magic_number(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "saved-page", [["About the job", "Lead a team."]])
    assert looks_like_pdf(path)


def test_ignores_a_plain_text_file(tmp_path: Path) -> None:
    path = tmp_path / "ad.txt"
    path.write_text("About the job\nYou will lead two squads.")
    assert not looks_like_pdf(path)


def test_extracts_the_advertisement(linkedin_pdf: Path) -> None:
    ad = extract_ad(linkedin_pdf)
    assert "You will lead two squads and own delivery." in ad.text
    # Body continuing onto a second page is kept.
    assert "Required: PHP and React" in ad.text


def test_stops_at_the_platform_furniture(linkedin_pdf: Path) -> None:
    ad = extract_ad(linkedin_pdf)
    assert "Some other role at Another Company" not in ad.text
    assert "Set alert for similar jobs" not in ad.text
    # Everything is still available when the anchors turn out to be wrong.
    assert "Some other role at Another Company" in ad.full_text


def test_drops_the_print_header_and_footer(linkedin_pdf: Path) -> None:
    ad = extract_ad(linkedin_pdf)
    assert "01/09/2026" not in ad.text
    assert "linkedin.com/jobs/view" not in ad.text
    assert "1/2" not in ad.text


def test_keeps_the_source_url_from_the_footer(linkedin_pdf: Path) -> None:
    ad = extract_ad(linkedin_pdf)
    assert ad.source_url == "https://www.linkedin.com/jobs/view/4417048804"


def test_keeps_the_posting_line(linkedin_pdf: Path) -> None:
    ad = extract_ad(linkedin_pdf)
    assert ad.posting_metadata is not None
    assert "Reposted 2 weeks ago" in ad.posting_metadata
    assert "72 people clicked apply" in ad.posting_metadata


def test_drops_navigation_chrome(linkedin_pdf: Path) -> None:
    ad = extract_ad(linkedin_pdf)
    assert "Take the next step in your job search" not in ad.text


def test_flags_a_description_saved_collapsed(tmp_path: Path) -> None:
    path = write_pdf(
        tmp_path / "collapsed.pdf",
        [
            [
                "About the job",
                "We are building the future of healthcare and we",
                "… more",
                _footer(1, 1),
            ]
        ],
    )
    assert extract_ad(path).truncated


def test_a_complete_description_is_not_flagged(linkedin_pdf: Path) -> None:
    assert not extract_ad(linkedin_pdf).truncated


def test_a_page_with_no_anchors_still_yields_its_text(tmp_path: Path) -> None:
    path = write_pdf(
        tmp_path / "recruiter.pdf",
        [["Engineering Manager, Sydney", "Five years of Python required.", _footer(1, 1)]],
    )
    ad = extract_ad(path)
    assert "Five years of Python required." in ad.text


def test_rejects_a_file_that_is_not_a_pdf(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not really a pdf")
    with pytest.raises(PDFError):
        extract_ad(path)


def test_rejects_a_pdf_with_no_text(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "scanned.pdf", [[]])
    with pytest.raises(PDFError) as excinfo:
        extract_ad(path)
    assert "scanned" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Page shapes that broke the first version
# --------------------------------------------------------------------------- #


def test_drops_a_header_a_clipped_line_fused_onto(tmp_path: Path) -> None:
    """A body line clipped by the top margin lands on the timestamp:
    "01/09/2026, 10:13g g Engineering Lead | Kira | LinkedIn"."""
    path = write_pdf(
        tmp_path / "clipped.pdf",
        [
            ["About the job", "The Engineering Lead owns technical direction.", _footer(1, 2)],
            [
                "01/09/2026, 10:13g g Engineering Lead | Kira | LinkedIn",
                "7+ years of software engineering experience.",
                _footer(2, 2),
            ],
        ],
    )
    ad = extract_ad(path)

    assert "7+ years of software engineering experience." in ad.text
    assert "01/09/2026" not in ad.text


def test_takes_the_source_url_by_majority(tmp_path: Path) -> None:
    """The same clipping fuses onto the footer URL. Four clean copies outvote
    the one that came back as ".../4417048804/O"."""
    path = write_pdf(
        tmp_path / "fused.pdf",
        [
            ["About the job", "Lead two squads.", _footer(1, 4).replace("/   1/4", "/O hit t  1/4")],
            ["Own the roadmap.", _footer(2, 4)],
            ["Coach engineers.", _footer(3, 4)],
            ["Set alert for similar jobs", _footer(4, 4)],
        ],
    )

    assert extract_ad(path).source_url == "https://www.linkedin.com/jobs/view/4417048804"


def test_stops_at_the_job_alert_heading(tmp_path: Path) -> None:
    """An agency ad has no "similar jobs" rail. Without this anchor a thousand
    characters of applicant charts ran into the parsed text."""
    path = write_pdf(
        tmp_path / "agency.pdf",
        [
            [
                "About the job",
                "You will lead two engineering squads.",
                "This job alert is on",
                "Engineering Manager, Greater Sydney Area On",
                "Applicants for this job",
                "43Applicants",
                _footer(1, 1),
            ]
        ],
    )
    ad = extract_ad(path)

    assert "You will lead two engineering squads." in ad.text
    assert "43Applicants" not in ad.text


def test_reaches_past_a_hiring_team_block_for_the_chips(tmp_path: Path) -> None:
    """The employment-type chip is the only place a LinkedIn page states
    full-time or contract. A twelve-line reach-back missed it whenever a
    "meet the hiring team" block sat between it and the description."""
    path = write_pdf(
        tmp_path / "hiring-team.pdf",
        [
            [
                "The Onset",
                "Engineering Manager",
                "Greater Sydney Area·1 month ago·43 applicants",
                "On-site Full-time",
                "No longer accepting applications",
                "People you can reach out to",
                "Ruby and others in your network Show all",
                "Meet the hiring team",
                "Sean McCartan • 2nd",
                "CEO/Founder I Onset Message",
                "Job poster",
                "Some other line",
                "And another",
                "And one more",
                "About the job",
                "You will lead two engineering squads.",
                _footer(1, 1),
            ]
        ],
    )
    ad = extract_ad(path)

    assert "On-site Full-time" in ad.text
    assert "The Onset" in ad.text
    assert "No longer accepting applications" in ad.text


# --------------------------------------------------------------------------- #
# Seek
# --------------------------------------------------------------------------- #

SEEK_HEADER = [
    "Open app",
    "Senior IT Project Manager",
    "Harvey Robinson Pty Ltd 3.8 View all jobs",
    "Sydney NSW (Hybrid)",
    "Programme & Project Management (Information & Communication Technology)",
    "Contract/Temp",
    "Exceptional Daily Rate",
    "Posted 26d ago High application volume",
    "You applied on 7 Aug 2026",
    "How you match",
    "Show all",
]

SEEK_FOOTER = [
    "Be careful",
    "Don't provide your bank or credit card details when applying for jobs.",
    "What can I earn as an IT Project Manager",
    "Job seekers Employers",
    "SEEK acknowledges the Traditional Custodians of the lands on which it operates",
    "Terms & conditions",
]


@pytest.fixture
def seek_pdf(tmp_path: Path) -> Path:
    return write_pdf(
        tmp_path / "seek.pdf",
        [
            SEEK_HEADER
            + [
                "Our client is expanding and they're looking for an experienced PM.",
                "A proven track record delivering complex IT projects.",
            ]
            + SEEK_FOOTER
            + [_footer(1, 1)]
        ],
    )


def test_keeps_a_seek_ad_that_has_no_heading(seek_pdf: Path) -> None:
    """Seek ads usually start straight into the copy — there is no
    "About the job" to anchor on."""
    ad = extract_ad(seek_pdf)

    assert "Our client is expanding" in ad.text
    assert "A proven track record delivering complex IT projects." in ad.text


def test_stops_at_the_seek_scam_warning(seek_pdf: Path) -> None:
    """Without an end anchor the model was handed Seek's whole footer, down to
    the acknowledgement of country."""
    ad = extract_ad(seek_pdf)

    assert "Be careful" not in ad.text
    assert "Traditional Custodians" not in ad.text
    assert "Terms & conditions" not in ad.text


def test_reads_the_seek_posting_line(seek_pdf: Path) -> None:
    """Seek states the posting age without LinkedIn's separator, and adds its
    own applicant-volume flag."""
    ad = extract_ad(seek_pdf)

    assert ad.posting_metadata == "Posted 26d ago High application volume"


def test_strips_the_rating_and_link_from_a_seek_company_line(seek_pdf: Path) -> None:
    ad = extract_ad(seek_pdf)

    assert "Harvey Robinson Pty Ltd" in ad.text
    assert "View all jobs" not in ad.text
    assert "Harvey Robinson Pty Ltd 3.8" not in ad.text


def test_keeps_a_body_line_ending_in_a_decimal(tmp_path: Path) -> None:
    """The rating strip is scoped to the company line. An ordinary sentence
    that happens to end in a decimal is left alone."""
    path = write_pdf(
        tmp_path / "decimal.pdf",
        [["Lifted the platform from version 2.9 to 3.4", "Be careful", _footer(1, 1)]],
    )

    assert "2.9 to 3.4" in extract_ad(path).text


def test_reaches_past_a_deep_seek_header(tmp_path: Path) -> None:
    """A Seek header is six lines deep before the posting line, where a
    LinkedIn one is two."""
    path = write_pdf(
        tmp_path / "deep.pdf",
        [SEEK_HEADER + ["About the role", "You will own delivery end to end.", _footer(1, 1)]],
    )
    ad = extract_ad(path)

    assert "Senior IT Project Manager" in ad.text
    assert "Harvey Robinson Pty Ltd" in ad.text
    assert "Contract/Temp" in ad.text
