"""Reading job ads out of saved web-page archives (.mhtml / .mht).

Chrome's "Webpage, Single File" format. Alan saves LinkedIn job pages this way,
which is permitted — it is a local file he already had open, not a fetch. This
module never makes a network request, and nothing here follows a URL found in
the archive. That is a hard rule in CLAUDE.md.

Decoding is all that is specific to the format. Stripping the platform
furniture and finding the advertisement inside what is left is shared with the
PDF adapter and lives in `adtext`.
"""

from __future__ import annotations

import email
import html
import re
from email import policy
from html.parser import HTMLParser
from pathlib import Path

from jobagent.adapters.adtext import (
    ExtractedAd,
    find_posting_metadata,
    isolate_ad,
    looks_truncated,
)

MHTML_SUFFIXES = {".mhtml", ".mht"}

# Chrome writes this header; Safari and Edge write the MIME-Version/Content-Type
# pair. Sniffing the head of the file catches archives saved under any name.
_SNIFF_MARKERS = (
    "Snapshot-Content-Location:",
    "From: <Saved by Blink>",
)

__all__ = ["MHTMLError", "ExtractedAd", "extract_ad", "looks_like_mhtml", "MHTML_SUFFIXES"]


class MHTMLError(Exception):
    """The archive could not be read or contained no usable HTML."""


def looks_like_mhtml(path: Path) -> bool:
    """True if this is a saved web archive, by suffix or by content."""
    if path.suffix.lower() in MHTML_SUFFIXES:
        return True
    try:
        with open(path, "rb") as handle:
            head = handle.read(2048).decode("ascii", errors="replace")
    except OSError:
        return False
    return any(marker in head for marker in _SNIFF_MARKERS)


def extract_ad(path: Path) -> ExtractedAd:
    """Pull the advertisement text out of a saved web-page archive."""
    try:
        with open(path, "rb") as handle:
            message = email.message_from_binary_file(handle, policy=policy.default)
    except OSError as exc:
        raise MHTMLError(f"Could not read {path}: {exc}") from exc
    except Exception as exc:  # malformed MIME
        raise MHTMLError(f"{path} is not a readable web archive: {exc}") from exc

    body = _first_html_part(message, path)
    lines = _to_lines(body)
    if not lines:
        raise MHTMLError(f"{path} contained HTML but no readable text.")

    text = isolate_ad(lines)
    return ExtractedAd(
        text=text,
        full_text="\n".join(lines),
        source_url=message.get("Snapshot-Content-Location"),
        page_title=message.get("Subject"),
        posting_metadata=find_posting_metadata(lines),
        truncated=looks_truncated(text),
    )


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #


def _first_html_part(message: email.message.Message, path: Path) -> str:
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        # Decode explicitly. Relying on the part's declared charset produces
        # replacement characters for every smart quote in a LinkedIn ad.
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")
    raise MHTMLError(f"{path} contains no HTML part — is it really a saved page?")


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    _BREAK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "tr", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP:
            self._depth += 1
        elif tag in self._BREAK:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._depth:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._depth and data.strip():
            self.chunks.append(data)


def _to_lines(body: str) -> list[str]:
    parser = _TextExtractor()
    parser.feed(body)
    text = html.unescape("".join(parser.chunks))
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return [line.strip() for line in text.splitlines() if line.strip()]
