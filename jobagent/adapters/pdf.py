"""Reading job ads out of PDFs printed from a job page.

Alan saves LinkedIn job pages with the browser's "Save as PDF". Like the .mhtml
route this is a local file from a page he already had open — no fetch, no
headless browser. Nothing here makes a network request or follows a URL found
in the document.

A printed page differs from a saved archive in two ways that matter:

* **Print furniture.** Chrome stamps a header (timestamp, page title) and a
  footer (source URL, "3/6") onto every page. The URL is worth keeping — it is
  the ad's own address — and the rest is noise that would otherwise appear
  a dozen times inside the extracted text.
* **Reading order.** Text is positioned, not sequenced. Extracted naively, the
  LinkedIn sidebar interleaves with the advertisement and the ad's second half
  can land after the "similar jobs" list that is supposed to terminate it.
  Layout-mode extraction reconstructs the visual order, which is the order the
  end anchors assume.

Layout mode has one known cost: words that straddle a style change come out
joined ("Backed byBlackbird", "work directly with theCEO"). It is left alone
deliberately — the obvious repair, splitting on a lowercase-uppercase boundary,
would also break CareGP, LinkedIn and JavaScript.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

from jobagent.adapters.adtext import (
    ExtractedAd,
    find_posting_metadata,
    isolate_ad,
    looks_truncated,
    normalise,
)

PDF_SUFFIXES = {".pdf"}
_MAGIC = b"%PDF-"

# Chrome's print header: "01/09/2026, 10:14   Engineering Manager | Xero | LinkedIn".
# No trailing \b: a body line clipped by the top margin fuses onto the
# timestamp ("01/09/2026, 10:13g g Engineering Lead | Kira | LinkedIn").
_PRINT_HEADER = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}")

# Chrome's print footer: the source URL, then "2/6". Both halves can be fused
# with whatever the page clipped at the bottom margin, so the URL is matched
# anywhere in the line rather than anchored.
_PRINT_FOOTER_URL = re.compile(r"https?://\S+")
# No leading \b: the bottom margin can clip a body line into the footer, and
# "…tdi ti1/6" has no word boundary before the page number.
_PAGE_NUMBER = re.compile(r"\d{1,3}/\d{1,3}\s*$")

__all__ = ["PDFError", "ExtractedAd", "extract_ad", "looks_like_pdf", "PDF_SUFFIXES"]


class PDFError(Exception):
    """The PDF could not be read or contained no readable text."""


def looks_like_pdf(path: Path) -> bool:
    """True if this is a PDF, by suffix or by magic number."""
    if path.suffix.lower() in PDF_SUFFIXES:
        return True
    try:
        with open(path, "rb") as handle:
            return handle.read(len(_MAGIC)) == _MAGIC
    except OSError:
        return False


def extract_ad(path: Path) -> ExtractedAd:
    """Pull the advertisement text out of a printed job page."""
    try:
        reader = PdfReader(str(path))
        pages = [
            page.extract_text(extraction_mode="layout") or "" for page in reader.pages
        ]
    except OSError as exc:
        raise PDFError(f"Could not read {path}: {exc}") from exc
    except Exception as exc:  # pypdf raises a wide range on a damaged file
        raise PDFError(f"{path} is not a readable PDF: {exc}") from exc

    if not pages:
        raise PDFError(f"{path} has no pages.")

    lines, source_url = _strip_print_furniture(pages)
    if not lines:
        raise PDFError(
            f"{path} contained no readable text — a scanned or image-only PDF "
            "cannot be parsed. Save the page as text or .mhtml instead."
        )

    text = isolate_ad(lines)
    return ExtractedAd(
        text=text,
        full_text="\n".join(lines),
        source_url=source_url,
        page_title=_page_title(reader),
        posting_metadata=find_posting_metadata(lines),
        truncated=looks_truncated(text),
    )


# --------------------------------------------------------------------------- #
# Print furniture
# --------------------------------------------------------------------------- #


def _strip_print_furniture(pages: list[str]) -> tuple[list[str], str | None]:
    """Drop the browser's per-page header and footer, keeping the source URL."""
    kept: list[str] = []
    urls: list[str] = []

    for page in pages:
        for raw in page.splitlines():
            line = re.sub(r"[ \t]+", " ", normalise(raw)).strip()
            if not line:
                continue
            if _PRINT_HEADER.match(line):
                continue
            found = _PRINT_FOOTER_URL.search(line)
            if found and _PAGE_NUMBER.search(line):
                urls.append(found.group())
                continue
            if _PAGE_NUMBER.fullmatch(line):
                continue
            kept.append(line)

    return kept, _source_url(urls)


def _source_url(urls: list[str]) -> str | None:
    """The ad's own address, from the footer every page repeats.

    Taken by majority rather than from the first page: a body line clipped by
    the bottom margin fuses onto the URL, and on the CareGP ad that turned
    page one's footer into ".../4395924490/O". Five clean copies outvote it.
    A single-page print has no such vote and keeps whatever it has.
    """
    if not urls:
        return None
    ranked = Counter(url.split("?")[0].rstrip("/") for url in urls)
    best = max(ranked.items(), key=lambda item: (item[1], -len(item[0])))
    return best[0]


def _page_title(reader: PdfReader) -> str | None:
    try:
        title = (reader.metadata or {}).get("/Title")
    except Exception:  # metadata is optional and frequently malformed
        return None
    return str(title) if title else None
