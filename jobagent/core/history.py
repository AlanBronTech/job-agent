"""What the pipeline already knows about a company, before a model is asked.

Free, and read entirely out of the store. It answers one question — *have I
been here before, and how did it go* — and answers it as fact. It does not
score, does not vote, and never reaches `check_constraints`: a company Alan
has approached before is history, not a filter, and the moment history starts
moving verdicts the tool is arguing him out of roles on fourteen data points.
If a company ever becomes an absolute skip, that is a decision Alan states in
`profile/assets.yaml` like every other hard filter, not one inferred here.

The warning cannot fire before the ad is parsed, because the company name is
what the parser reads out of it. That costs ~$0.08. It fires before the $0.20
score and the $0.30 generate, which is where the money and the day actually go.
"""

from __future__ import annotations

import re
import sqlite3

from jobagent.core import store
from jobagent.core.models import CompanyHistory, JobDescription, PriorEncounter

# Dropped from the end of a company name. An employer is the same employer
# with or without its legal form, and the parser copies whatever the ad wrote.
_LEGAL_FORMS = frozenset(
    {
        "pty", "ltd", "limited", "inc", "incorporated", "llc", "llp", "plc",
        "corp", "corporation", "co", "company", "gmbh", "ag", "sa", "nv", "bv",
    }
)

# Dropped from the front. "The Onset" and "Onset" are one company.
_LEADING_NOISE = frozenset({"the"})


def normalise_company(name: str | None) -> str:
    """Reduce a company name to the tokens that identify the employer.

    Parenthesised asides go first — "Toshiba Global Commerce Solutions (TGCS)"
    is one employer written two ways in a single string.
    """
    if not name:
        return ""
    without_asides = re.sub(r"\([^)]*\)", " ", name)
    tokens = re.findall(r"[a-z0-9]+", without_asides.casefold())
    while tokens and tokens[0] in _LEADING_NOISE:
        tokens.pop(0)
    while tokens and tokens[-1] in _LEGAL_FORMS:
        tokens.pop()
    return " ".join(tokens)


def same_company(left: str | None, right: str | None) -> bool:
    """Are these two ads from the same employer.

    A prefix match, so "Nuix" and "Nuix Technologies" are one company. That is
    deliberately looser than the on-site location filter, which is literal to
    the point of pedantry — and the reason is that the two mistakes cost
    different amounts. A false positive here prints a line Alan reads and
    dismisses. A false negative is the whole failure being fixed: he pays for a
    score and spends a day on the company that screened him out last week.
    """
    left_tokens = normalise_company(left).split()
    right_tokens = normalise_company(right).split()
    if not left_tokens or not right_tokens:
        return False
    shorter, longer = sorted((left_tokens, right_tokens), key=len)
    return longer[: len(shorter)] == shorter


def company_history(conn: sqlite3.Connection, jd: JobDescription) -> CompanyHistory:
    """Every earlier ad in the pipeline from ``jd``'s company, newest first.

    ``jd`` itself is excluded by id, so this is safe to call after it has been
    saved. An ad with no company name has no history — matching on title alone
    would put every "Engineering Manager" in the store on one warning.
    """
    if not jd.company:
        return CompanyHistory(company="", encounters=[])

    encounters = [
        PriorEncounter(
            jd_id=other.id,
            title=other.title,
            ingested_at=other.ingested_at,
            same_posting=_same_posting(jd, other),
            status=application.status if application else None,
            worth_applying=application.worth_applying if application else None,
            worth_why=application.worth_why if application else "",
        )
        for other, application in store.list_jds_with_applications(conn)
        if other.id is not None
        and other.id != jd.id
        and same_company(jd.company, other.company)
    ]
    encounters.sort(key=lambda encounter: encounter.ingested_at, reverse=True)
    return CompanyHistory(company=jd.company, encounters=encounters)


def _same_posting(jd: JobDescription, other: JobDescription) -> bool:
    """The identical ad, ingested twice — not merely the same employer.

    Compared on the source URL, which is the only stable identity a saved page
    carries. Titles get edited between reposts; the trailing slash LinkedIn
    sometimes writes does not mean a different job.
    """
    if not jd.source_url or not other.source_url:
        return False
    return jd.source_url.rstrip("/") == other.source_url.rstrip("/")
