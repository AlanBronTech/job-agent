"""Is this ad a job Alan has already applied for, and how recently?

Pure: it is handed everything it needs and reads nothing. The decision about
what to do with a match (refuse, ask, honour an overrule) belongs to
`services.reapply`; this only says what matches and how old it is.

A match is one of two kinds (spec 002, FR-008, FR-008a):

- **same**: equal requisition numbers, or the identical ad URL. Proof.
- **possibly_same**: same company and same role title, and the requisition
  numbers do not settle it, because at least one side has none. Alan answers
  yes or no. The spec first said "neither side has a number"; the worked
  example had the number only on the earlier application (from the employer's
  receipt email) and none in the reposted ad, and that rule would have missed
  it. Different numbers on both sides mean different jobs, whatever the title.

Only applications with a date count, and the outcome is irrelevant: a
rejection or a withdrawal is still an application to that job. A stored ad that
has been scored or applied for, carrying the same requisition number, also
counts, so two copies of one job in a batch cannot both be scored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from jobagent.core.history import same_company
from jobagent.core.models import Application, JobDescription, OutsideApplication
from jobagent.core.requisition import normalise_requisition


@dataclass(frozen=True)
class Match:
    kind: str  # "same" | "possibly_same"
    against: str  # "application:<jd_id>" | "outside:<id>" | "ad:<jd_id>"
    company: str
    title: str
    requisition_id: str | None
    applied_on: date
    age_days: int
    reason: str  # "requisition" | "url" | "title"


def normalise_title(title: str | None) -> str:
    """Case and punctuation folded; words, including seniority, kept."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).split())


def match(
    jd: JobDescription,
    *,
    tracked: list[tuple[JobDescription, Application]],
    outside: list[OutsideApplication],
    scored: list[tuple[JobDescription, date]] = (),
    window_days: int | None,
    today: date,
) -> Match | None:
    """The strongest match inside the window, or None.

    `tracked` pairs a stored ad with its application; `scored` pairs a stored
    ad with the date it was scored, and is only used for requisition matches.
    `window_days=None` means the rule is off.
    """
    if window_days is None:
        return None

    found: list[Match] = []

    for other, application in tracked:
        if other.id == jd.id or application.applied_on is None:
            continue
        found += _compare(
            jd,
            against=f"application:{other.id}",
            company=other.company,
            title=other.title,
            requisition_id=other.requisition_id,
            source_url=other.source_url,
            on=application.applied_on,
            today=today,
        )

    for record in outside:
        if record.linked_jd_id is not None:  # its ad's application stands for it
            continue
        found += _compare(
            jd,
            against=f"outside:{record.id}",
            company=record.company,
            title=record.title,
            requisition_id=record.requisition_id,
            source_url=None,
            on=record.applied_on,
            today=today,
        )

    for other, on in scored:
        if other.id == jd.id or not (other.requisition_id and jd.requisition_id):
            continue
        if normalise_requisition(other.requisition_id) == normalise_requisition(jd.requisition_id):
            found.append(
                _make("same", f"ad:{other.id}", other.company, other.title,
                      other.requisition_id, on, today, "requisition")
            )

    inside = [m for m in found if m.age_days < window_days]
    if not inside:
        return None
    # "same" beats "possibly_same"; then the most recent.
    return sorted(inside, key=lambda m: (m.kind != "same", m.age_days))[0]


def _compare(jd, *, against, company, title, requisition_id, source_url, on, today) -> list[Match]:
    ours, theirs = jd.requisition_id, requisition_id
    if ours and theirs:
        if normalise_requisition(ours) == normalise_requisition(theirs):
            return [_make("same", against, company, title, theirs, on, today, "requisition")]
        return []  # different numbers: different jobs, whatever the title
    if jd.source_url and source_url and jd.source_url == source_url:
        return [_make("same", against, company, title, theirs, on, today, "url")]
    if same_company(jd.company, company) and normalise_title(jd.title) == normalise_title(title):
        return [_make("possibly_same", against, company, title, theirs, on, today, "title")]
    return []


def _make(kind, against, company, title, requisition_id, on, today, reason) -> Match:
    return Match(
        kind=kind,
        against=against,
        company=company or "",
        title=title or "",
        requisition_id=requisition_id,
        applied_on=on,
        age_days=(today - on).days,
        reason=reason,
    )
