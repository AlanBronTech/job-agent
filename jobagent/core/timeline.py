"""The career in date order, computed rather than asked for (REVIEW-2026-10-16 D3).

The scorer was given every role with its dates and still wrote that two contract
roles "precede and run alongside his management roles" when both came years
after the first management role. Order is arithmetic on dates, and arithmetic is
what code is for: `render` hands the scorer the order already worked out, and
`order_claims` checks any sentence that asserts an order against the dates.

A role is management when the profile says so (`people_management`) or, when it
is silent, when its title names a management job. The title rule is a fallback;
the flag is the fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobagent.core.models import Profile, Visibility
from jobagent.core.validation import employer_aliases

_MANAGEMENT_TITLE = re.compile(
    r"manager|head of|\bcto\b|chief technology|director|team lead", re.IGNORECASE
)


@dataclass(frozen=True)
class Span:
    id: str
    company: str
    title: str
    start: tuple[int, int]
    end: tuple[int, int] | None  # None: present
    management: bool

    @property
    def label(self) -> str:
        return f"{self.title} · {self.company}"


def _period(value: str | None) -> tuple[int, int] | None:
    if value is None or str(value).lower() == "present":
        return None
    year, _, month = str(value).partition("-")
    return int(year), int(month or 1)


def is_management(role) -> bool:
    flag = getattr(role, "people_management", None)
    if flag is not None:
        return bool(flag)
    return bool(_MANAGEMENT_TITLE.search(role.title))


def roles_in_order(profile: Profile) -> list[Span]:
    """Employment roles, earliest start first."""
    spans = []
    for role in profile.roles.roles:
        if role.visibility is Visibility.scorer_only:
            continue
        spans.append(Span(role.id, role.company, role.title, _period(role.start),
                          _period(role.end), is_management(role)))
    return sorted(spans, key=lambda s: s.start)


def _fmt(period: tuple[int, int] | None) -> str:
    return "present" if period is None else f"{period[0]}-{period[1]:02d}"


def render(profile: Profile) -> str:
    """The `{timeline}` block for the scoring prompt."""
    spans = roles_in_order(profile)
    lines = [
        f"{_fmt(s.start)} to {_fmt(s.end)}  {s.label}  "
        f"[{'management' if s.management else 'individual contributor'}]"
        for s in spans
    ]
    first = next((s for s in spans if s.management), None)
    if first:
        lines.append(f"First management role starts {_fmt(first.start)} ({first.company}).")
    ics_after = [s.company for s in spans if not s.management and first and s.start > first.start]
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
