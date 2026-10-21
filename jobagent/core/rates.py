"""Day rates, read out of an ad in code (REVIEW-2026-10-18, task 7).

A contract is quoted per day, and the parser is told to leave a day rate out
of `salary_range`'s numbers and keep it in `raw`. So the salary floor never
sees it, and every contract ad was asked "what is the band? The floor is
$150,000" — the wrong question for the wrong unit. The rate is pulled out
here instead, the way the requisition number is: by pattern, not by asking a
model, because a hard filter is arithmetic over a decision Alan has made.

Deliberately narrow: an amount must sit next to a per-day phrase. "Competitive
daily rate" has no amount and yields None, which the filter reports as
unknown — the honest answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobagent.core.models import JobDescription, WorkType

# A plausible day rate: $300 to $5,000, with or without the dollar sign.
_AMOUNT = r"\$?\s?(\d{1}[,.]?\d{3}|\d{3})(?![\d,.%])"
_PER_DAY = r"(?:per\s+day|/\s?day|a\s+day|p\.?\s?d\b\.?|daily\s+rate)"
# Between an amount and "per day", only words about the amount itself.
_FILLER = r"(?:[\s,()+]|aud|inc(?:luding|l)?\.?|ex(?:cl(?:uding)?)?\.?|plus|super(?:annuation)?|gst)*?"
_RANGE = re.compile(
    _AMOUNT + r"\s*(?:-|–|—|to)\s*" + _AMOUNT + _FILLER + _PER_DAY, re.IGNORECASE
)
_AFTER = re.compile(_AMOUNT + _FILLER + _PER_DAY, re.IGNORECASE)
_BEFORE = re.compile(r"(?:day|daily)\s+rate[^.\n\d$]{0,25}" + _AMOUNT, re.IGNORECASE)
_INC_SUPER = re.compile(r"\b(?:inc(?:l(?:uding|\.)?)?|incl?\.?)\s*super", re.IGNORECASE)
_PLUS_SUPER = re.compile(r"(?:\+|plus|excl(?:uding|\.)?)\s*super", re.IGNORECASE)

LOW, HIGH = 300, 5000


@dataclass(frozen=True)
class DayRate:
    low: int
    high: int
    # True for "including super", False for "+ super", None when unstated.
    includes_super: bool | None
    text: str


def day_rate(jd: JobDescription) -> DayRate | None:
    """The day rate the ad states, from its salary text first, then its body."""
    raw = jd.salary_range.raw if jd.salary_range and jd.salary_range.raw else ""
    for source in (raw, jd.raw_text):
        found = find_day_rate(source)
        if found is not None:
            return found
    return None


def find_day_rate(text: str) -> DayRate | None:
    for pattern in (_RANGE, _BEFORE, _AFTER):
        for match in pattern.finditer(text or ""):
            amounts = [_number(g) for g in match.groups() if g]
            if not amounts or not all(LOW <= a <= HIGH for a in amounts):
                continue
            window = text[match.start(): match.end() + 40]
            return DayRate(
                low=min(amounts),
                high=max(amounts),
                includes_super=_super(window),
                text=" ".join(match.group(0).split()),
            )
    return None


def is_contract(jd: JobDescription) -> bool:
    """Contract or fixed-term: bought for a defined piece of work."""
    return jd.work_type in (WorkType.contract, WorkType.fixed_term)


def _number(value: str) -> int:
    return int(re.sub(r"[^\d]", "", value))


def _super(window: str) -> bool | None:
    if _INC_SUPER.search(window):
        return True
    if _PLUS_SUPER.search(window):
        return False
    return None
