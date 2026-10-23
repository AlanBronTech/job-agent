"""Job-alert emails into a short list of jobs worth a look, and Alan's decision on each.

`ingest` reads the parsed emails into `alert_listings`: one row per job id,
however many emails it arrived in. Each new listing is judged by
`core/alerts.judge` and then checked against what the pipeline already holds,
so an ad already in JobAgent, applied for, or decided on before is not
suggested again. `pending` is what is left to look at; `decide` records what
Alan made of it; `report` says how good the suggestions were, which is the
only way the title rules get better.

Nothing here opens a job page. Alan opens the link, gives the ad a once-over,
and saves it for `jd add` himself; `link_ad` then marks the listing saved.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from jobagent.adapters import mailbox
from jobagent.core import alerts as core
from jobagent.core import store
from jobagent.core.history import same_company
from jobagent.core.models import (
    AlertDecision,
    AlertListing,
    AlertRules,
    AlertVerdict,
    JobDescription,
)
from jobagent.core.profile import ProfileError, load_profile
from jobagent.core.reapply import normalise_title
from jobagent.services.refusals import ProfileInvalid, ProfileMissing, Refusal
from jobagent.services.workspace import Workspace

LAST_FETCH = "alerts_last_fetch"
# A first run, with no record of the last one, looks back this far.
FIRST_LOOKBACK = timedelta(days=7)
# Alerts are for fresh jobs: an undecided listing older than this drops off
# the pending list (it stays in the table and in `--all`).
STALE_AFTER = timedelta(days=21)
PENDING = (AlertVerdict.suggest, AlertVerdict.maybe)


class NoMailbox(Refusal):
    """GMAIL_ADDRESS or GMAIL_APP_PASSWORD is not set."""


class MailboxFailed(Refusal):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NoAlertRules(Refusal):
    """assets.yaml has no `alerts:` section."""


class NoSuchListing(Refusal):
    def __init__(self, listing_id: int) -> None:
        super().__init__(f"no alert listing with id {listing_id}")
        self.listing_id = listing_id


@dataclass
class IngestResult:
    emails: int = 0
    listings: int = 0
    new: int = 0
    suggested: int = 0
    # Alert emails that gave no listings at all: a changed email layout shows
    # up here, rather than as a quiet day with nothing suggested.
    unread: list[str] = field(default_factory=list)


@dataclass
class Pending:
    listing: AlertListing
    history: list[str]


@dataclass
class Report:
    by_verdict: Counter
    by_decision: dict[str, Counter]
    not_relevant: list[AlertListing]
    not_qualified: list[AlertListing]
    skip_reasons: Counter


# --------------------------------------------------------------------------- #
# Reading the emails in
# --------------------------------------------------------------------------- #


def default_since(ws: Workspace, today: date) -> date:
    """The day before the last fetch, so nothing between runs is missed; else a week."""
    with store.open_store(ws.db_path) as conn:
        last = store.get_meta(conn, LAST_FETCH)
    if last:
        return date.fromisoformat(last[:10]) - timedelta(days=1)
    return today - FIRST_LOOKBACK


def fetch(
    ws: Workspace, *, address: str | None, app_password: str | None, since: date, now: datetime
) -> IngestResult:
    """Read the alert emails from Gmail and ingest them. Read-only on the mailbox."""
    if not (address and app_password):
        raise NoMailbox()
    rules = _rules(ws)
    try:
        mails = mailbox.fetch_gmail(address, app_password, since)
    except mailbox.MailboxError as exc:
        raise MailboxFailed(str(exc)) from exc
    return ingest(ws, mails, now=now, rules=rules)


def ingest(ws: Workspace, mails: list, *, now: datetime, rules: AlertRules | None = None) -> IngestResult:
    rules = rules or _rules(ws)
    filters = _filters(ws)
    result = IngestResult(emails=len(mails))
    with store.open_store(ws.db_path) as conn:
        ads = store.list_jds(conn)
        applications = {a.jd_id: a for a in store.list_applications(conn)}
        outside = store.list_outside(conn)
        for mail in mails:
            listings = core.parse_email(mail.sender, mail.text)
            if not listings and _looks_like_jobs(mail.subject):
                result.unread.append(mail.subject)
            for parsed in listings:
                result.listings += 1
                seen = mail.received if mail.received.tzinfo else mail.received.replace(tzinfo=timezone.utc)
                row = store.find_alert(conn, parsed.source, parsed.job_id)
                if row is None:
                    row = AlertListing(
                        source=parsed.source, job_id=parsed.job_id, title=parsed.title,
                        company=parsed.company, location=parsed.location, pay=parsed.pay,
                        url=parsed.url, first_seen=seen, last_seen=seen,
                    )
                    result.new += 1
                else:
                    row.times_seen += 1
                    row.first_seen = min(row.first_seen, seen)
                    row.last_seen = max(row.last_seen, seen)
                    row.pay = row.pay or parsed.pay
                    row.location = row.location or parsed.location
                if row.decision is None:
                    _judge(row, parsed, rules, filters, conn, ads, applications, outside)
                store.save_alert(conn, row)
        store.set_meta(conn, LAST_FETCH, now.isoformat())
        result.suggested = len(_pending_rows(store.list_alerts(conn), now))
    return result


def _judge(row, parsed, rules, filters, conn, ads, applications, outside) -> None:
    verdict = core.judge(parsed, rules, min_salary=filters[0], min_day_rate=filters[1])
    row.verdict, row.reason = verdict.verdict, verdict.reason
    if row.verdict is AlertVerdict.skip:
        return
    known = _already_known(row, conn, ads, applications, outside)
    if known:
        row.verdict, row.reason = AlertVerdict.skip, known


def _already_known(row: AlertListing, conn, ads, applications, outside) -> str | None:
    """Why this job need not be suggested: it is in the pipeline, or was decided on."""
    for ad in ads:
        if core.job_key(ad.source_url) == (row.source, row.job_id):
            row.jd_id = ad.id
            return f"already in JobAgent as JD {ad.id}{_status(applications.get(ad.id))}"
    title = normalise_title(row.title)
    for ad in ads:
        if same_company(row.company, ad.company or ad.posted_by) and normalise_title(ad.title) == title:
            return f"possibly JD {ad.id}{_status(applications.get(ad.id))}: same company and title"
    for record in outside:
        if same_company(row.company, record.company) and normalise_title(record.title) == title:
            return f"possibly your outside application of {record.applied_on:%-d %b %Y}"
    for other in store.list_alerts(conn):
        if other.id == row.id or normalise_title(other.title) != title:
            continue
        if not same_company(row.company, other.company):
            continue
        if other.decision not in (None, AlertDecision.later):
            return f"decided before as {other.decision.value} (listing {other.id})"
        if other.verdict in PENDING:
            return f"same job as listing {other.id} ({other.source})"
    return None


def _status(application) -> str:
    return f" ({application.status.value})" if application else ""


def _looks_like_jobs(subject: str) -> bool:
    s = subject.lower()
    return any(w in s for w in ("job", "role", "hiring", " at "))


def _rules(ws: Workspace) -> AlertRules:
    rules = _profile(ws).assets.alerts
    if rules is None:
        raise NoAlertRules()
    return rules


def _filters(ws: Workspace) -> tuple[int | None, int | None]:
    f = _profile(ws).assets.target_filters
    return f.min_salary_aud, f.min_day_rate_aud


def _profile(ws: Workspace):
    if ws.profile_dir is None:
        raise ProfileMissing()
    try:
        return load_profile(ws.profile_dir)
    except ProfileError as exc:
        raise ProfileInvalid(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Looking and deciding
# --------------------------------------------------------------------------- #


def pending(ws: Workspace, now: datetime) -> list[Pending]:
    """Suggested listings still to look at: suggest before maybe, newest first."""
    with store.open_store(ws.db_path) as conn:
        rows = _pending_rows(store.list_alerts(conn), now)
        ads = store.list_jds(conn)
        applications = {a.jd_id: a for a in store.list_applications(conn)}
    return [Pending(row, _history(row, ads, applications)) for row in rows]


def pending_count(ws: Workspace, now: datetime) -> int:
    """How many suggestions wait for a look. Cheap: no profile, no mailbox."""
    with store.open_store(ws.db_path) as conn:
        return len(_pending_rows(store.list_alerts(conn), now))


def last_fetch(ws: Workspace) -> datetime | None:
    with store.open_store(ws.db_path) as conn:
        value = store.get_meta(conn, LAST_FETCH)
    return datetime.fromisoformat(value) if value else None


def _pending_rows(rows: list[AlertListing], now: datetime) -> list[AlertListing]:
    cutoff = now - STALE_AFTER
    keep = [
        r for r in rows
        if r.verdict in PENDING
        and r.decision in (None, AlertDecision.later)
        and r.last_seen >= cutoff
    ]
    return sorted(keep, key=lambda r: (r.verdict is not AlertVerdict.suggest, -r.first_seen.timestamp()))


def _history(row: AlertListing, ads: list[JobDescription], applications) -> list[str]:
    """Earlier ads from this company: reported, never used to drop a listing."""
    out = []
    for ad in ads:
        if row.company and same_company(row.company, ad.company or ad.posted_by):
            out.append(f"JD {ad.id} {ad.title}{_status(applications.get(ad.id))}")
    return out[:3]


def listings(ws: Workspace, *, verdict: AlertVerdict | None = None) -> list[AlertListing]:
    with store.open_store(ws.db_path) as conn:
        rows = store.list_alerts(conn)
    return [r for r in rows if verdict is None or r.verdict is verdict]


def decide(
    ws: Workspace,
    listing_ids: list[int],
    decision: AlertDecision,
    *,
    note: str = "",
    jd_id: int | None = None,
    now: datetime,
) -> list[AlertListing]:
    """Record a decision on one or more listings. All ids are checked before any is written."""
    with store.open_store(ws.db_path) as conn:
        rows = []
        for listing_id in listing_ids:
            row = store.get_alert(conn, listing_id)
            if row is None:
                raise NoSuchListing(listing_id)
            rows.append(row)
        for row in rows:
            row.decision, row.decided_at = decision, now
            if note.strip():
                row.note = note.strip()
            if jd_id is not None:
                row.jd_id = jd_id
            store.save_alert(conn, row)
    return rows


def link_ad(ws: Workspace, jd: JobDescription, now: datetime) -> AlertListing | None:
    """An ad just added from a saved page: if an alert suggested it, it was saved."""
    key = core.job_key(jd.source_url)
    if key is None or jd.id is None:
        return None
    with store.open_store(ws.db_path) as conn:
        row = store.find_alert(conn, *key)
        if row is None:
            return None
        row.jd_id = jd.id
        if row.decision in (None, AlertDecision.later):
            row.decision, row.decided_at = AlertDecision.saved, now
        store.save_alert(conn, row)
    return row


def report(ws: Workspace) -> Report:
    rows = listings(ws)
    by_decision: dict[str, Counter] = {}
    for verdict in AlertVerdict:
        by_decision[verdict.value] = Counter(
            (r.decision.value if r.decision else "undecided") for r in rows if r.verdict is verdict
        )
    return Report(
        by_verdict=Counter(r.verdict.value for r in rows),
        by_decision=by_decision,
        not_relevant=[r for r in rows if r.decision is AlertDecision.not_relevant],
        not_qualified=[r for r in rows if r.decision is AlertDecision.not_qualified],
        skip_reasons=Counter(_reason_kind(r.reason) for r in rows if r.verdict is AlertVerdict.skip),
    )


def _reason_kind(reason: str) -> str:
    for prefix in ("title:", "already in JobAgent", "possibly", "decided before", "same job",
                   "pay up to", "day rate up to", "hands-on role", "title is not"):
        if reason.startswith(prefix):
            return reason if prefix == "title:" else prefix
    return reason or "(none)"
