"""Shared handling of saved job-ad text, whatever it was saved from.

A LinkedIn page saved as .mhtml and the same page printed to PDF differ in how
the text is *decoded*, not in what surrounds it. Both arrive as a list of lines
in which the advertisement is a minority of the content, wrapped in navigation,
"people also viewed", applicant charts and footer links. Everything that is
common to both — where the ad starts, where it stops, which lines are platform
furniture, and where the posting line is — lives here so the two adapters
cannot drift apart on it.

Nothing in this module reads a file or makes a network request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Where the advertisement starts, on the platforms Alan uses.
BODY_ANCHORS = ("About the job", "Job description", "About the role")

# Where it stops and the platform's own furniture resumes. Which of these
# appears depends on the ad: an agency posting with no "similar jobs" rail ran
# a thousand characters of applicant charts into the parsed text before the
# job-alert and comparison headings were added here.
END_ANCHORS = (
    "Set alert for similar jobs",
    "This job alert is on",
    "Insights about this job",
    "Exclusive Job Seeker Insights",
    "People also viewed",
    "Similar jobs",
    "More jobs",
    "Put your best foot forward",
    "See how you compare to other applicants",
    "Applicants for this job",
)

# Navigation and applicant-flow chrome that sits between the anchors.
JUNK_LINES = frozenset(
    {
        "home", "my network", "jobs", "messaging", "notifications", "me",
        "for business", "learning", "try premium", "advertise",
        "take the next step in your job search", "practice an interview",
        "application status", "view resume", "go to company site",
        "easy apply", "save", "saved", "share", "show more", "show less",
        "… more", "...more", "more",
    }
)

JUNK_PREFIXES = (
    "skip to",
    "applied on company site",
    "application submitted",
    "promoted by hirer",
)

# A metadata line looks like "<place>·<age>·<applicants>". Match on the
# separator plus at least one signal word so ordinary prose never qualifies.
_META_SIGNALS = ("ago", "applicant", "clicked apply", "reposted")

# What a LinkedIn description looks like when it was saved with the "…more"
# toggle still collapsed. The text behind it is lazy-loaded and genuinely
# absent from the capture, so a silent return here yields a confident, wrong
# parse of half an advertisement.
_TRUNCATION_MARKERS = ("… more", "…more", "... more", "...more")


@dataclass
class ExtractedAd:
    """What a saved job page yields, however it was saved."""

    text: str
    """The advertisement, platform furniture removed. What gets parsed."""

    full_text: str
    """Everything on the page. Kept for when the anchors miss."""

    source_url: str | None
    """The page's own URL, stored opaquely. Never fetched."""

    page_title: str | None
    posting_metadata: str | None
    """Platform's posting line, verbatim — age of ad, applicant count."""

    truncated: bool = False
    """The capture ends at a "…more" toggle: the ad is only partly present."""


# How far above "About the job" the posting line may sit and still be taken as
# the start of the ad. A "meet the hiring team" block pushes it well back.
_MAX_HEAD_REACH = 40


def isolate_ad(lines: list[str]) -> str:
    """Trim to the advertisement. Returns everything if the anchors miss —
    a degraded parse beats refusing the file."""
    anchor = index_of(lines, BODY_ANCHORS)
    if anchor is None:
        return "\n".join(drop_junk(lines))

    head = drop_junk(lines[_head_start(lines, anchor) : anchor])
    end = index_of(lines, END_ANCHORS, after=anchor) or len(lines)
    return "\n".join(head + lines[anchor:end])


def _head_start(lines: list[str], anchor: int) -> int:
    """Where to start reaching back for company, title and posting line.

    The posting line is the reliable marker. Directly above it sit the company
    and the title; directly below it the "Hybrid · Full-time" chips, which are
    a LinkedIn page's only statement of employment type. A fixed twelve-line
    window missed all of that on a page carrying a "meet the hiring team"
    block, so reach back past the posting line as well when it is close enough
    to be this ad's rather than a neighbouring one's.
    """
    default = anchor - 12
    posting = posting_metadata_index(lines)
    if posting is not None and 0 < anchor - posting <= _MAX_HEAD_REACH:
        return max(0, min(default, posting - 3))
    return max(0, default)


def index_of(lines: list[str], needles: tuple[str, ...], after: int = -1) -> int | None:
    for index in range(after + 1, len(lines)):
        if any(needle in lines[index] for needle in needles):
            return index
    return None


def drop_junk(lines: list[str]) -> list[str]:
    kept = []
    for line in lines:
        lowered = line.lower()
        if lowered in JUNK_LINES:
            continue
        if any(lowered.startswith(prefix) for prefix in JUNK_PREFIXES):
            continue
        # "3Notifications", "0 notifications"
        if re.fullmatch(r"\d*\s*notifications?", lowered):
            continue
        kept.append(line)
    return kept


def find_posting_metadata(lines: list[str]) -> str | None:
    index = posting_metadata_index(lines)
    return None if index is None else lines[index]


def posting_metadata_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines[:60]):
        if "·" not in line:
            continue
        lowered = line.lower()
        if any(signal in lowered for signal in _META_SIGNALS):
            return index
    return None


def looks_truncated(ad_text: str) -> bool:
    """True if the ad text stops at an unexpanded "…more" toggle.

    Only the tail is examined. "Show more" appears all over a LinkedIn page as
    ordinary furniture; it means the description was cut short only when it is
    the last thing in the advertisement.
    """
    tail = ad_text.rstrip().lower()[-40:]
    return any(marker in tail for marker in _TRUNCATION_MARKERS)
