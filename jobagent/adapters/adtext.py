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
import unicodedata
from dataclasses import dataclass

# Where the advertisement starts, on the platforms Alan uses. Seek ads often
# have no heading at all — the copy simply begins — which is why a missing
# anchor has to degrade to "keep everything" rather than fail.
BODY_ANCHORS = (
    "About the job",
    "About the role",
    "About this role",
    "Job description",
)

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
    # Seek. "Be careful" heads the scam warning that closes every ad, and is
    # the only reliable end marker on a platform whose ads have no heading.
    "Be careful",
    "What can I earn as",
    "More about this company",
    "Your application will include the following questions",
    "Employer questions",
    "SEEK acknowledges the Traditional Custodians",
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
        # Seek
        "open app", "responsive hirer", "how you match", "show all",
        "salary match", "see more detailed salary information",
        "learn how to protect yourself", "quick apply", "job seekers employers",
    }
)

JUNK_PREFIXES = (
    "skip to",
    "applied on company site",
    "application submitted",
    "promoted by hirer",
)

# Seek chrome, and one line of it that cannot simply be dropped: the company
# name shares its line with a star rating and "View all jobs", which together
# turn a company into "United Fasteners Australia Pty Ltd 3.8 View all jobs".
# The rating is only stripped on a line that carried the link, so an ordinary
# sentence ending in a decimal is left alone.
JUNK_SUFFIXES = (" View all jobs",)
_SEEK_RATING = re.compile(r"\s\d\.\d$")

# On LinkedIn a metadata line looks like "<place>·<age>·<applicants>". Match on
# the separator plus at least one signal word so ordinary prose never qualifies.
_META_SIGNALS = ("ago", "applicant", "clicked apply", "reposted")

# Seek states the same thing without a separator: "Posted 30d+ ago High
# application volume". The volume flag is Seek's own, and it is triage signal
# of exactly the kind the posting line is kept for.
_SEEK_POSTING = re.compile(r"^Posted\s+\d+[dhm]?\+?\s+ago\b", re.IGNORECASE)

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
    """Trim to the advertisement. Keeps everything above the end anchor if the
    ad has no heading — a degraded parse beats refusing the file."""
    anchor = index_of(lines, BODY_ANCHORS)
    if anchor is None:
        # Seek ads usually start straight into the copy. The tail still has to
        # go: without it the model was handed Seek's whole footer, down to the
        # acknowledgement of country.
        end = index_of(lines, END_ANCHORS) or len(lines)
        return "\n".join(drop_junk(lines[:end]))

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

    Six lines above it, because a Seek header is deeper than a LinkedIn one:
    title, company, location, classification, work type and salary all sit
    between the title and the posting line. Overshooting is cheap — what is
    above a job header is navigation, and drop_junk takes it.
    """
    default = anchor - 12
    posting = posting_metadata_index(lines)
    if posting is not None and 0 < anchor - posting <= _MAX_HEAD_REACH:
        return max(0, min(default, posting - 6))
    return max(0, default)


def index_of(lines: list[str], needles: tuple[str, ...], after: int = -1) -> int | None:
    for index in range(after + 1, len(lines)):
        if any(needle in lines[index] for needle in needles):
            return index
    return None


def drop_junk(lines: list[str]) -> list[str]:
    kept = []
    for line in lines:
        for suffix in JUNK_SUFFIXES:
            if line.endswith(suffix):
                line = _SEEK_RATING.sub("", line[: -len(suffix)].rstrip())
        lowered = line.lower()
        if not lowered:
            continue
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
        if _SEEK_POSTING.match(line):
            return index
        if "·" not in line:
            continue
        lowered = line.lower()
        if any(signal in lowered for signal in _META_SIGNALS):
            return index
    return None


def normalise(text: str) -> str:
    """Collapse the typographic ligatures a PDF hands back.

    Printed Seek ads come out full of "proﬁle", "greenﬁeld" and "oﬀers" — the
    single ﬁ/ﬀ glyphs, not the letter pairs. Any downstream string match
    against the ad silently fails on them.
    """
    return unicodedata.normalize("NFKC", text)


def looks_truncated(ad_text: str) -> bool:
    """True if the ad text stops at an unexpanded "…more" toggle.

    Only the tail is examined. "Show more" appears all over a LinkedIn page as
    ordinary furniture; it means the description was cut short only when it is
    the last thing in the advertisement.
    """
    tail = ad_text.rstrip().lower()[-40:]
    return any(marker in tail for marker in _TRUNCATION_MARKERS)
