"""Reading job ads out of saved web-page archives (.mhtml / .mht).

Chrome's "Webpage, Single File" format. Alan saves LinkedIn job pages this way,
which is permitted — it is a local file he already had open, not a fetch. This
module never makes a network request, and nothing here follows a URL found in
the archive. That is a hard rule in CLAUDE.md.

Two jobs beyond decoding:

* **Strip the platform furniture.** A saved LinkedIn page is ~6 MB and roughly
  95% navigation, "people also viewed", company insights and hiring charts. Fed
  whole to a model it costs tokens and invites hallucinated requirements.
* **Keep the posting metadata.** The line reading
  ``Sydney, NSW, Australia·Reposted 2 weeks ago·72 people clicked apply`` is not
  part of the advertisement, but "how long has this been open and how many have
  applied" is real triage signal — an ad live for five months says something the
  ad text never will. It is captured verbatim rather than parsed, because two
  samples is not enough to know the shape of the wording.
"""

from __future__ import annotations

import email
import html
import re
from dataclasses import dataclass
from email import policy
from html.parser import HTMLParser
from pathlib import Path

MHTML_SUFFIXES = {".mhtml", ".mht"}

# Chrome writes this header; Safari and Edge write the MIME-Version/Content-Type
# pair. Sniffing the head of the file catches archives saved under any name.
_SNIFF_MARKERS = (
    "Snapshot-Content-Location:",
    "From: <Saved by Blink>",
)

# Where the advertisement starts, on the platforms Alan uses.
_BODY_ANCHORS = ("About the job", "Job description", "About the role")

# Where it stops and the platform's own furniture resumes.
_END_ANCHORS = (
    "Set alert for similar jobs",
    "Insights about this job",
    "People also viewed",
    "Similar jobs",
    "More jobs",
)

# Navigation and applicant-flow chrome that sits between the anchors.
_JUNK_LINES = frozenset(
    {
        "home", "my network", "jobs", "messaging", "notifications", "me",
        "for business", "learning", "try premium", "advertise",
        "take the next step in your job search", "practice an interview",
        "application status", "view resume", "go to company site",
        "easy apply", "save", "saved", "share", "show more", "show less",
        "… more", "...more", "more",
    }
)

_JUNK_PREFIXES = (
    "skip to",
    "applied on company site",
    "application submitted",
    "promoted by hirer",
)

# A metadata line looks like "<place>·<age>·<applicants>". Match on the
# separator plus at least one signal word so ordinary prose never qualifies.
_META_SIGNALS = ("ago", "applicant", "clicked apply", "reposted")


class MHTMLError(Exception):
    """The archive could not be read or contained no usable HTML."""


@dataclass
class ExtractedAd:
    """What a saved job page yields."""

    text: str
    """The advertisement, platform furniture removed. What gets parsed."""

    full_text: str
    """Everything on the page. Kept for when the anchors miss."""

    source_url: str | None
    """The page's own URL, stored opaquely. Never fetched."""

    page_title: str | None
    posting_metadata: str | None
    """Platform's posting line, verbatim — age of ad, applicant count."""


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

    return ExtractedAd(
        text=_isolate_ad(lines),
        full_text="\n".join(lines),
        source_url=message.get("Snapshot-Content-Location"),
        page_title=message.get("Subject"),
        posting_metadata=_find_posting_metadata(lines),
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


# --------------------------------------------------------------------------- #
# Isolating the advertisement
# --------------------------------------------------------------------------- #


def _isolate_ad(lines: list[str]) -> str:
    """Trim to the advertisement. Returns everything if the anchors miss —
    a degraded parse beats refusing the file."""
    anchor = _index_of(lines, _BODY_ANCHORS)
    if anchor is None:
        return "\n".join(_drop_junk(lines))

    # Reach back for the company, title and posting line above "About the job".
    head = _drop_junk(lines[max(0, anchor - 12) : anchor])
    end = _index_of(lines, _END_ANCHORS, after=anchor) or len(lines)
    return "\n".join(head + lines[anchor:end])


def _index_of(
    lines: list[str], needles: tuple[str, ...], after: int = -1
) -> int | None:
    for index in range(after + 1, len(lines)):
        if any(needle in lines[index] for needle in needles):
            return index
    return None


def _drop_junk(lines: list[str]) -> list[str]:
    kept = []
    for line in lines:
        lowered = line.lower()
        if lowered in _JUNK_LINES:
            continue
        if any(lowered.startswith(prefix) for prefix in _JUNK_PREFIXES):
            continue
        # "3Notifications", "0 notifications"
        if re.fullmatch(r"\d*\s*notifications?", lowered):
            continue
        kept.append(line)
    return kept


def _find_posting_metadata(lines: list[str]) -> str | None:
    for line in lines[:60]:
        if "·" not in line:
            continue
        lowered = line.lower()
        if any(signal in lowered for signal in _META_SIGNALS):
            return line
    return None
