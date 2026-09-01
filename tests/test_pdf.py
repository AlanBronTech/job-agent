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
