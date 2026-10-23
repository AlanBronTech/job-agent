"""How many pages a .docx renders to, measured rather than guessed.

python-docx has no layout engine, so the only honest page count comes from
something that lays the document out. LibreOffice does, headless, and
substitutes Carlito for Calibri — a metric-compatible font, so line breaks and
page breaks match Word's. Measured on 20 real resumes on 2026-10-23: 1.74 to
2.59 pages.

Optional: without LibreOffice the count is None and nothing is checked. The
count is fractional — whole pages plus how far down the last page the text
reaches — because "1.5 to 1.75 pages" is the target, not a page number.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

_MAC_SOFFICE = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
# A4 in points, and the master resume's top and bottom margins (1.32cm, 1.23cm).
_PAGE_HEIGHT = 842.0
_TOP_MARGIN = 37.4
_BOTTOM_MARGIN = 34.9
_TIMEOUT_SECONDS = 90


def soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    return str(_MAC_SOFFICE) if _MAC_SOFFICE.exists() else None


def count_pages(docx: Path) -> float | None:
    """Pages, to two decimals; None when LibreOffice is absent or the render fails."""
    binary = soffice()
    if binary is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(
                [binary, f"-env:UserInstallation=file://{tmp}/profile", "--headless",
                 "--convert-to", "pdf", "--outdir", tmp, str(docx)],
                check=True, capture_output=True, timeout=_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        pdf = Path(tmp) / f"{docx.stem}.pdf"
        if not pdf.exists():
            return None
        return pdf_pages(pdf)


def pdf_pages(pdf: Path) -> float | None:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(pdf))
        heights: list[float] = []
        reader.pages[-1].extract_text(
            visitor_text=lambda text, _cm, tm, _fd, _fs: heights.append(tm[5]) if text.strip() else None
        )
    except Exception:  # noqa: BLE001 - a page count is advice; never fail the run on it
        return None
    whole = len(reader.pages) - 1
    if not heights:
        return float(whole)
    top = _PAGE_HEIGHT - _TOP_MARGIN
    used = (top - min(heights)) / (top - _BOTTOM_MARGIN)
    return round(whole + max(0.0, min(1.0, used)), 2)
