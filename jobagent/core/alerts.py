"""Job-alert emails from SEEK and LinkedIn: read the listings, decide which deserve a look.

Pure. A message's text goes in; listings, and a verdict on each, come out. The
emails are Alan's own mail and reading them is not access to either site; the
job pages they link to are never opened (CLAUDE.md, hard rule 1). Everything a
listing says is what the email said: title, company, location, sometimes pay.

Common sense, not a model. A title alone is too little for even the cheap
screen to judge, and most of the value is arithmetic: the same job arrives in
several emails a day for a week, and some of it is already in the pipeline.
What is left is filtered by title words Alan keeps in `assets.yaml` and by the
pay floors he has already set. A listing is suggested, suggested as a maybe,
or skipped with its reason, so the filter can be audited.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobagent.core.models import AlertRules, AlertVerdict

SEEK = "seek"
LINKEDIN = "linkedin"

_SEEK_JOB = re.compile(r"https?://(?:au\.seek\.com|(?:www\.)?seek\.com\.au)/job/(\d+)")
_LINKEDIN_JOB = re.compile(r"https?://(?:[a-z]+\.)?linkedin\.com/(?:comm/)?jobs/view/(\d+)")
_LINKEDIN_VIEW = re.compile(r"^View(?: job:)?\s*(https://\S*linkedin\.com/\S*jobs/view/(\d+)\S*)")

_SEEK_BADGE = re.compile(r"^(?:(?:very )?strong applicant|new|featured|be an early applicant)$", re.I)
_SEEK_STOP = re.compile(
    r"^(?:logo|jobs you may have missed|matches your preference.*|explore now|"
    r"take your next career step|your destination for.*|hi \w+,?|based on your saved search.*|"
    r"we.ve$|view all matching jobs|.*\bnew jobs?\b.*)$",
    re.I,
)
_LINKEDIN_BADGES = {
    "top applicant", "apply with resume & profile", "this company is actively hiring",
    "fast growing", "be an early applicant", "actively recruiting", "promoted", "easy apply",
    "early applicant", "in your network",
}
_LOCATION = re.compile(r"\b(?:NSW|VIC|QLD|ACT|SA|WA|TAS|NT|Sydney|Melbourne|Brisbane|Canberra|Perth|Adelaide|Hobart|Remote|Australia)\b")


@dataclass(frozen=True)
class Listing:
    source: str
    job_id: str
    title: str
    company: str
    location: str
    pay: str

    @property
    def url(self) -> str:
        """The plain job URL, without the alert's tracking parameters."""
        if self.source == SEEK:
            return f"https://au.seek.com/job/{self.job_id}"
        return f"https://www.linkedin.com/jobs/view/{self.job_id}/"

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.job_id)


# --------------------------------------------------------------------------- #
# Reading the emails
# --------------------------------------------------------------------------- #


_CLOSED = re.compile(
    r"no longer accepting applications|applications have closed|"
    r"this job is no longer (?:advertised|available)|this job has expired|job ad has expired",
    re.I,
)


def says_closed(page_text: str) -> bool:
    """Whether a saved job page says the ad has stopped taking applications."""
    return bool(_CLOSED.search(page_text or ""))


def has_job_links(text: str) -> bool:
    """Whether an email links to individual jobs at all: if it does and nothing
    was read from it, the layout has changed."""
    return bool(_SEEK_JOB.search(text) or _LINKEDIN_JOB.search(text))


def source_of(sender: str) -> str | None:
    sender = sender.lower()
    if "seek.com.au" in sender or "seek.com" in sender:
        return SEEK
    if "linkedin.com" in sender:
        return LINKEDIN
    return None


def parse_email(sender: str, text: str) -> list[Listing]:
    """Every job listing in one alert email's plain text. Unknown senders give none."""
    source = source_of(sender)
    if source == SEEK:
        return parse_seek(text)
    if source == LINKEDIN:
        return parse_linkedin(text)
    return []


def parse_seek(text: str) -> list[Listing]:
    """SEEK's saved-search email: title, advertiser, badges, location, pay, then the link.

    Each listing is read backwards from its link, stopping at the previous
    link, a logo, or one of the email's own headings.
    """
    lines = [line.strip() for line in text.splitlines()]
    out: list[Listing] = []
    for index, line in enumerate(lines):
        match = _SEEK_JOB.search(line)
        if not match or not line.startswith("["):
            continue
        block: list[str] = []
        for previous in reversed(lines[:index]):
            if not previous:
                continue
            if previous.startswith(("[", "http")) or _SEEK_STOP.match(previous):
                break
            block.insert(0, previous)
        listing = _seek_listing(match.group(1), block)
        if listing:
            out.append(listing)
    return _unique(out)


def _seek_listing(job_id: str, block: list[str]) -> Listing | None:
    block = [b for b in block if not _SEEK_BADGE.match(b) and not b.lower().startswith("posted on ")]
    if len(block) < 2:
        return None
    title = re.sub(r"(?<=[a-z)])New$", "", block[0]).strip()
    company, rest = block[1], block[2:]
    location = next((r for r in rest if _LOCATION.search(r)), "")
    pay = " ".join(r for r in rest if r != location)
    return Listing(SEEK, job_id, title, company, location, pay)


def parse_linkedin(text: str) -> list[Listing]:
    """LinkedIn's alert, recommendation and "similar jobs" emails.

    Title, company, location and badges, then "View job: <link>". The career-
    insights email writes "Company · Location" on one line and "View<link>".
    """
    lines = [line.strip() for line in text.splitlines()]
    out: list[Listing] = []
    for index, line in enumerate(lines):
        match = _LINKEDIN_VIEW.match(line)
        if not match:
            continue
        block: list[str] = []
        for previous in reversed(lines[:index]):
            if previous.startswith("---") or "http" in previous or previous.endswith("----"):
                break
            if previous and previous.lower() not in _LINKEDIN_BADGES:
                block.insert(0, previous)
        listing = _linkedin_listing(match.group(2), block)
        if listing:
            out.append(listing)
    return _unique(out)


def _linkedin_listing(job_id: str, block: list[str]) -> Listing | None:
    if not block:
        return None
    title = block[0]
    if len(block) >= 3:
        return Listing(LINKEDIN, job_id, title, block[1], block[2], "")
    if len(block) == 2 and " · " in block[1]:
        company, _, location = block[1].partition(" · ")
        # "LMG · Sydney, NSWLMG · Sydney, NSW (Hybrid)": the line repeats itself.
        if company in location:
            location = location[: location.index(company)]
        return Listing(LINKEDIN, job_id, title, company.strip(), location.strip(), "")
    if len(block) == 2:
        return Listing(LINKEDIN, job_id, title, block[1], "", "")
    return None


def _unique(listings: list[Listing]) -> list[Listing]:
    seen: dict[tuple[str, str], Listing] = {}
    for listing in listings:
        seen.setdefault(listing.key, listing)
    return list(seen.values())


def job_key(url: str | None) -> tuple[str, str] | None:
    """(source, job id) for a SEEK or LinkedIn job URL, as stored on an ad."""
    if not url:
        return None
    if match := _SEEK_JOB.search(url):
        return (SEEK, match.group(1))
    if match := _LINKEDIN_JOB.search(url):
        return (LINKEDIN, match.group(1))
    return None


# --------------------------------------------------------------------------- #
# Pay
# --------------------------------------------------------------------------- #

_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k\b)?", re.I)
_DAILY = re.compile(r"\bday\b|\bdaily\b|p\.\s?d\b|\bpd\b|ped day|/day", re.I)


@dataclass(frozen=True)
class Pay:
    amount: int
    daily: bool


def read_pay(text: str) -> Pay | None:
    """The top of the stated band, as a day rate or an annual salary. None if no figure.

    The top, not the bottom: a band that reaches the floor is worth a look.
    """
    if not text:
        return None
    daily = bool(_DAILY.search(text))
    values = []
    for number, k in _NUMBER.findall(text):
        value = float(number.replace(",", ""))
        if k:
            value *= 1000
            if value > 2_000_000:  # "$133348.0k": already in dollars
                value /= 1000
        values.append(value)
    if daily:
        rates = [v for v in values if 300 <= v <= 5000]
        return Pay(int(max(rates)), True) if rates else None
    salaries = [v for v in values if 30_000 <= v <= 2_000_000]
    return Pay(int(max(salaries)), False) if salaries else None


# --------------------------------------------------------------------------- #
# The filter
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Verdict:
    verdict: AlertVerdict
    reason: str


def _words(text: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9+#]+", " ", text.lower()).split()) + " "


def _hit(title: str, terms: list[str]) -> str | None:
    folded = _words(title)
    return next((t for t in terms if _words(t) in folded), None)


def judge(
    listing: Listing,
    rules: AlertRules,
    *,
    min_salary: int | None,
    min_day_rate: int | None,
) -> Verdict:
    """Suggest, maybe or skip, from the title and any stated pay."""
    if term := _hit(listing.title, rules.never_titles):
        return Verdict(AlertVerdict.skip, f"title: {term}")
    pay = read_pay(listing.pay)
    if pay and pay.daily and min_day_rate and pay.amount < min_day_rate:
        return Verdict(AlertVerdict.skip, f"day rate up to ${pay.amount:,} is under ${min_day_rate:,}")
    if pay and not pay.daily and min_salary and pay.amount < min_salary:
        return Verdict(AlertVerdict.skip, f"pay up to ${pay.amount:,} is under ${min_salary:,}")
    if term := _hit(listing.title, rules.want_titles):
        return Verdict(AlertVerdict.suggest, f"title: {term}")
    if term := _hit(listing.title, rules.maybe_titles):
        return Verdict(AlertVerdict.maybe, f"title: {term}")
    if term := _hit(listing.title, rules.contract_titles):
        if pay and pay.daily and (min_day_rate is None or pay.amount >= min_day_rate):
            return Verdict(AlertVerdict.maybe, f"contract, ${pay.amount:,}/day: {term}")
        return Verdict(AlertVerdict.skip, f"hands-on role with no day rate: {term}")
    return Verdict(AlertVerdict.skip, "title is not a target role")
