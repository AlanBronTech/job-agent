"""The career in date order, computed rather than asked for (REVIEW-2026-10-16 D3).

The scorer was given every role with its dates and still wrote that two contract
roles "precede and run alongside his management roles" when both came years
after the first management role. Order is arithmetic on dates, and arithmetic is
what code is for: `render` hands the scorer the order already worked out, and
`order_claims` checks any sentence that asserts an order against the dates.

A role is management when the profile says so (`people_management`) or, when it
is silent, when its title names a management job. The title rule is a fallback;
the flag is the fact. A founder venture joins the timeline only when flagged:
"Co-founder & CTO" says nothing about a team. Leadership in `earlier_career`
is undated, so it cannot be added up; it is named instead, and the total is
called what it is, a minimum (2026-10-26: the dated total was read as the
whole career, and a 5+ year bar marked partial).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from jobagent.core.models import Profile, Visibility
from jobagent.core.validation import employer_aliases

# Titles that count as managing engineers, for the timeline's tags and for
# management tenure. Matched case-insensitively as substrings of the title.
# Set `people_management` on a role whose title undersells it, rather than
# widening this list.
EM_TITLES: tuple[str, ...] = (
    "engineering manager",
    "software development manager",
    "development manager",
    "head of engineering",
    "director of engineering",
    "chief technology officer",
    "cto",
    "team lead",
)


@dataclass(frozen=True)
class Span:
    id: str
    company: str
    title: str
    start: tuple[int, int]
    end: tuple[int, int] | None  # None: present
    management: bool
    managed_from: tuple[int, int] | None = None  # later than start, when it is

    @property
    def managing_from(self) -> tuple[int, int]:
        return max(self.start, self.managed_from or self.start)

    @property
    def label(self) -> str:
        return f"{self.title} · {self.company}"


def _period(value: str | None) -> tuple[int, int] | None:
    if value is None or str(value).lower() == "present":
        return None
    year, _, month = str(value).partition("-")
    return int(year), int(month or 1)


def is_management(role, titles: tuple[str, ...] = EM_TITLES) -> bool:
    flag = getattr(role, "people_management", None)
    if flag is not None:
        return bool(flag)
    title = role.title.lower()
    return any(re.search(rf"\b{re.escape(t)}\b", title) for t in titles)


def management_months(profile: Profile, *, today: date | None = None) -> int:
    """Months spent in management roles, added up across roles, overlaps counted once.

    REVIEW-2026-10-16 D4: "2+ years as an Engineering Manager" was marked
    partial because no single role was two years long. The requirement is
    cumulative, and adding is arithmetic, so it is done here and handed over.
    """
    today = today or date.today()
    months: set[tuple[int, int]] = set()
    for span in roles_in_order(profile):
        if not span.management:
            continue
        end = span.end or (today.year, today.month)
        y, m = span.managing_from
        while (y, m) < end:
            months.add((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return len(months)


def roles_in_order(profile: Profile) -> list[Span]:
    """Employment roles, and dated ventures that managed people, earliest start first."""
    spans = []
    for role in profile.roles.roles:
        if role.visibility is Visibility.scorer_only:
            continue
        spans.append(Span(role.id, role.company, role.title, _period(role.start),
                          _period(role.end), is_management(role)))
    for venture in profile.roles.founder_track_record:
        if venture.people_management and venture.start:
            spans.append(Span(venture.id, venture.company, venture.role, _period(venture.start),
                              _period(venture.end), True, _period(venture.management_from)))
    return sorted(spans, key=lambda s: s.start)


def undated_leadership(profile: Profile) -> list[str]:
    """Earlier roles that led people, which no total can include."""
    return [f"{e.company} ({e.role})" for e in profile.roles.earlier_career if e.people_management]


def _fmt(period: tuple[int, int] | None) -> str:
    return "present" if period is None else f"{period[0]}-{period[1]:02d}"


def render(profile: Profile) -> str:
    """The `{timeline}` block for the scoring prompt."""
    spans = roles_in_order(profile)
    lines = [
        f"{_fmt(s.start)} to {_fmt(s.end)}  {s.label}  "
        f"[{'management' if s.management else 'individual contributor'}"
        + (f", managing people from {_fmt(s.managed_from)}" if s.managed_from else "") + "]"
        for s in spans
    ]
    first = min((s for s in spans if s.management), key=lambda s: s.managing_from, default=None)
    if first:
        lines.append(f"First management role starts {_fmt(first.managing_from)} ({first.company}).")
        total = management_months(profile)
        years, rest = divmod(total, 12)
        lines.append(
            f"Management tenure, dated roles added up: {total} months ({years} years"
            + (f" {rest} months" if rest else "") + ")."
        )
        earlier = undated_leadership(profile)
        if earlier:
            lines.append(
                "Leadership before these, undated and so not in the total: "
                + ", ".join(earlier) + ". The total is a minimum, not the career."
            )
    ics_after = [s.company for s in spans if not s.management and first and s.start > first.managing_from]
    if ics_after:
        lines.append(
            "Individual-contributor roles that began after the first management role: "
            + ", ".join(ics_after) + "."
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Checking what a text says about order
# --------------------------------------------------------------------------- #

_BEFORE = re.compile(r"\b(?:preced\w*|before|prior to|earlier than|predat\w*)\b", re.IGNORECASE)
_AFTER = re.compile(r"\b(?:after|follow\w*|later than|succeed\w*|postdat\w*)\b", re.IGNORECASE)
_MANAGEMENT_CATEGORY = re.compile(r"\bmanage\w* roles?\b|\bmanagement\b", re.IGNORECASE)
_IC_CATEGORY = re.compile(r"\bIC roles?\b|\bindividual[- ]contributor roles?\b", re.IGNORECASE)


def order_claims(text: str, profile: Profile) -> list[str]:
    """Sentences in `text` whose claim about order the dates contradict.

    A sentence counts when it has an order word and names roles on both sides
    of it: employers, or "management roles" / "IC roles" as a group. "A
    precedes B" is false if any role in A starts no earlier than the earliest
    role in B; "A follows B" is false if any role in A starts no later than it.
    """
    spans = roles_in_order(profile)
    aliases = [(alias, span) for span in spans for alias in employer_aliases(span.company)]
    problems = []
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        match = _BEFORE.search(sentence) or _AFTER.search(sentence)
        if match is None:
            continue
        before_claim = bool(_BEFORE.search(sentence)) and (
            not _AFTER.search(sentence) or _BEFORE.search(sentence).start() < _AFTER.search(sentence).start()
        )
        word = (_BEFORE if before_claim else _AFTER).search(sentence)
        left = _mentions(sentence[: word.start()], aliases, spans)
        right = _mentions(sentence[word.end():], aliases, spans) - left
        if not left or not right:
            continue
        earliest_right = min(s.start for s in right)
        if before_claim:
            wrong = [s for s in left if s.start >= earliest_right]
        else:
            wrong = [s for s in left if s.start <= earliest_right]
        if wrong:
            started = ", ".join(f"{s.company} started {_fmt(s.start)}"
                                for s in sorted(wrong, key=lambda s: s.start))
            problems.append(
                f"\"{sentence.strip()}\" — the dates say otherwise: {started}, "
                f"{'not before' if before_claim else 'not after'} {_fmt(earliest_right)}."
            )
    return problems


def _mentions(fragment: str, aliases, spans) -> set[Span]:
    found = {span for alias, span in aliases
             if re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", fragment)}
    if _MANAGEMENT_CATEGORY.search(fragment):
        found |= {s for s in spans if s.management}
    if _IC_CATEGORY.search(fragment):
        found |= {s for s in spans if not s.management}
    return found


_YEARS_AT = re.compile(r"\byears\s+(?:at|with|in)\b(?P<rest>[^.;]*)", re.IGNORECASE)


def duration_claims(text: str, profile: Profile, *, today: date | None = None) -> list[str]:
    """"Years at X" where the dates give X less than two years (D8).

    A suggested interview answer said the work he is proudest of "took years
    at" two employers, one of which he worked at for seven months. Every
    employer named after "years at" is checked.
    """
    today = today or date.today()
    spans = roles_in_order(profile)
    problems = []
    for match in _YEARS_AT.finditer(text):
        rest = match.group("rest")
        for span in spans:
            if not any(re.search(rf"(?<![\w-]){re.escape(a)}(?![\w-])", rest)
                       for a in employer_aliases(span.company)):
                continue
            end = span.end or (today.year, today.month)
            months = (end[0] - span.start[0]) * 12 + end[1] - span.start[1]
            if months < 24:
                problems.append(
                    f"\"{match.group(0).strip()}\" — {span.company} lasted {months} months "
                    f"({_fmt(span.start)} to {_fmt(span.end)}), not years."
                )
    return problems
