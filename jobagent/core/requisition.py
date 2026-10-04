"""The employer's own reference number for a job, read out of the ad's text.

Why it matters: a repost gets a new URL and usually the same title, but keeps
its requisition number. Without it, "is this the job I applied for in May?"
had no reliable answer, and the tool scored and wrote documents for one before
the employer's portal showed the earlier application (spec 002).

Done in code, not by the model: free, repeatable, testable, and it can be run
over every stored ad without a paid re-parse. A model that sees no number may
supply a plausible one; this cannot.

Rules (spec 002, research R1): the value is kept exactly as written; it must
contain a digit, so "Job type: Permanent" is never a number; more than one
distinct number in an ad gives None rather than a guess.
"""

from __future__ import annotations

import re

_VALUE = r"([A-Za-z0-9][A-Za-z0-9_\-/]{1,24}[A-Za-z0-9])"

_PATTERNS = [
    # Workday: JR_000123, JR-000123, JR000123.
    re.compile(r"\b(JR[_-]?\d{4,})\b", re.IGNORECASE),
    # A label with an id word, separator optional: "Req ID 45871", "Job No. A-1".
    re.compile(
        r"\b(?:job\s+)?(?:requisition|req|reference|ref|vacancy|position|job)\s*"
        r"(?:id|no\.?|number|code|#)\s*[:#.]?\s*" + _VALUE,
        re.IGNORECASE,
    ),
    # A bare label with a separator: "Reference: ABC-2026-77", "Job reference: X1".
    re.compile(
        r"\b(?:job\s+)?(?:requisition|reference|ref|vacancy)\s*[:#]\s*" + _VALUE,
        re.IGNORECASE,
    ),
]


def normalise_requisition(value: str) -> str:
    """Comparison form: upper case, separators removed. JR_000123 == jr-000123."""
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def requisition_candidates(text: str) -> list[str]:
    """Every distinct requisition number found, first spelling kept, in order."""
    seen: dict[str, str] = {}
    for pattern in _PATTERNS:
        for match in pattern.finditer(text or ""):
            value = match.group(1)
            if not re.search(r"\d", value):
                continue
            seen.setdefault(normalise_requisition(value), value)
    return list(seen.values())


def extract_requisition(text: str) -> str | None:
    """The ad's one requisition number, or None if it has none or several."""
    candidates = requisition_candidates(text)
    return candidates[0] if len(candidates) == 1 else None
