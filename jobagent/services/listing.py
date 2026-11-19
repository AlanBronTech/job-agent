"""What the list and detail pages show. Read-only; costs nothing.

Everything here is already in the store or on disk. The one derived fact is
`stale`: an assessment older than the ad's last amendment was scored against
text that has since been replaced, and the free read is the one most likely
to be trusted without thinking, so it has to say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from jobagent.adapters.document_store import OutputFolders
from jobagent.core import history, store
from jobagent.core.models import (
    MasterChoice,
    MasterResume,
    Application,
    ApplicationStatus,
    CompanyHistory,
    FitAssessment,
    JobDescription,
    RoleClassification,
    Verdict,
    WorkType,
)
from jobagent.core.masters import CustomAdvice
from jobagent.services import masters, outputs, revise, sent
from jobagent.services.refusals import NoSuchAd
from jobagent.services.workspace import Workspace


@dataclass
class AdRow:
    jd_id: int
    title: str
    company: str | None
    captured: datetime
    verdict: Verdict | None
    overall_score: int | None
    recruiter_score: int | None
    status: ApplicationStatus | None
    has_documents: bool
    stale: bool
    requisition_id: str | None = None
    work_type: WorkType | None = None
    applied_on: date | None = None
    # When the application was last changed; None with no application.
    updated_at: datetime | None = None

    @property
    def last_activity(self) -> datetime:
        return self.updated_at or self.captured


@dataclass
class AdDetail:
    jd: JobDescription
    assessment: FitAssessment | None
    stale: bool
    history: CompanyHistory
    folders: OutputFolders
    application: Application | None
    role_kind: RoleClassification | None = None
    # What was sent, each against its generated copy (services.sent.Comparison).
    sent: list = field(default_factory=list)
    # What Alan knows that the ad does not say; given to every writer.
    context: str | None = None
    # Documents in the current folder a revision can start from (RevisionPlan).
    revisable: list = field(default_factory=list)
    # The master resume to send (services.masters); None without a registry.
    master: MasterChoice | None = None
    # Every master, for the pipeline form's "resume sent" choice.
    masters: list[MasterResume] = field(default_factory=list)
    # Whether a custom resume is worth generating beside the master (free).
    custom: CustomAdvice | None = None


def ad_rows(ws: Workspace, *, today: date, sort: str = "date") -> list[AdRow]:
    """Every ad, newest first, or by hiring-manager score with unscored last."""
    with store.open_store(ws.db_path) as conn:
        pairs = store.list_jds_with_applications(conn)
        scored = {
            jd.id: (
                store.latest_assessment(conn, jd.id),
                store.latest_assessment_stale(conn, jd.id),
            )
            for jd, _ in pairs
        }
    on_disk = outputs.index_all(ws, [jd for jd, _ in pairs], today)

    rows = []
    for jd, application in pairs:
        assessment, stale = scored[jd.id]
        rows.append(
            AdRow(
                jd_id=jd.id,
                title=jd.title,
                company=jd.company or jd.posted_by,
                captured=jd.ingested_at,
                verdict=assessment.verdict if assessment else None,
                overall_score=assessment.overall_score if assessment else None,
                recruiter_score=assessment.recruiter_screen_score if assessment else None,
                status=application.status if application else None,
                has_documents=on_disk[jd.id].any,
                stale=bool(assessment) and stale,
                requisition_id=jd.requisition_id,
                work_type=jd.work_type,
                applied_on=application.applied_on if application else None,
                updated_at=application.updated_at if application else None,
            )
        )
    return sort_rows(rows, sort)


# --------------------------------------------------------------------------- #
# The Jobs page's view: which rows, in what order (Alan, 2026-11-19)
# --------------------------------------------------------------------------- #

S = ApplicationStatus
IN_PROGRESS = frozenset({S.recruiter_call, S.interview_1, S.interview_2, S.offer})
UNDECIDED = frozenset({None, S.identified})
OPEN = UNDECIDED | {S.applied} | IN_PROGRESS
# Applied this long ago with nothing back: chase it or close it as no reply.
FOLLOW_UP_DAYS = 30

# Each stage: its label, and whether a row belongs. Ordered as the dropdown
# shows them; a label starting "↳ " is a part of the closed group above it.
STAGES: dict[str, tuple[str, object]] = {
    "open": ("Open", lambda r, today: r.status in OPEN),
    "decide": ("↳ To decide", lambda r, today: r.status in UNDECIDED),
    "applied": ("↳ Applied, waiting", lambda r, today: r.status is S.applied),
    "followup": ("↳ Follow-up due", lambda r, today: _follow_up_due(r, today)),
    "progress": ("↳ In progress", lambda r, today: r.status in IN_PROGRESS),
    "closed": ("Closed", lambda r, today: r.status not in OPEN),
    "rejected": ("↳ Rejected", lambda r, today: r.status in {S.rejected_screen, S.rejected_after_interview}),
    "rejected_screen": ("↳ Rejected at screening", lambda r, today: r.status is S.rejected_screen),
    "rejected_after_interview": ("↳ Rejected after interview",
                                 lambda r, today: r.status is S.rejected_after_interview),
    "no_reply": ("↳ No reply", lambda r, today: r.status in {S.applied_no_reply, S.ghosted_after_contact}),
    "not_applied": ("↳ Chose not to apply", lambda r, today: r.status is S.not_applied),
    "withdrew": ("↳ Withdrew", lambda r, today: r.status is S.withdrew),
    "all": ("All", lambda r, today: True),
}
DEFAULT_STAGE = "open"

SORTS: dict[str, str] = {
    "date": "newest",
    "oldest": "oldest",
    "score": "score high–low",
    "score_low": "score low–high",
    "activity": "last activity",
}
DAYS = (7, 30, 90)
VERDICTS: dict[str, str] = {
    "apply": "apply",
    "apply_with_caveats": "apply with caveats",
    "skip": "skip",
    "unscored": "not scored",
}
WORK_TYPES: dict[str, str] = {"contract": "contract or fixed term", "permanent": "permanent"}


@dataclass(frozen=True)
class JobsView:
    """What the Jobs page was asked for. Unknown values fall back to the default."""

    stage: str = DEFAULT_STAGE
    sort: str = "date"
    days: int | None = None
    verdict: str = ""
    work: str = ""
    q: str = ""

    @classmethod
    def from_params(cls, params) -> JobsView:
        days = params.get("days") or ""
        return cls(
            stage=_one_of(params.get("stage"), STAGES, DEFAULT_STAGE),
            sort=_one_of(params.get("sort"), SORTS, "date"),
            days=int(days) if days.isdigit() and int(days) in DAYS else None,
            verdict=_one_of(params.get("verdict"), VERDICTS, ""),
            work=_one_of(params.get("work"), WORK_TYPES, ""),
            q=(params.get("q") or "").strip()[:100],
        )

    @property
    def narrowed(self) -> bool:
        """Anything beyond the stage: a date range, verdict, work type or search."""
        return bool(self.days or self.verdict or self.work or self.q)


def view_rows(rows: list[AdRow], view: JobsView, today: date) -> list[AdRow]:
    """The rows the view asks for, in its order. Free; the rows are already read."""
    in_stage = STAGES[view.stage][1]
    since = today - timedelta(days=view.days) if view.days else None
    needle = view.q.casefold()
    kept = [
        r for r in rows
        if in_stage(r, today)
        and (since is None or r.captured.date() >= since)
        and _verdict_matches(r, view.verdict)
        and _work_matches(r, view.work)
        and (not needle or needle in f"{r.title} {r.company or ''} {r.requisition_id or ''}".casefold())
    ]
    return sort_rows(kept, view.sort)


def stage_counts(rows: list[AdRow], today: date) -> dict[str, int]:
    """How many rows each stage holds, before any other filter."""
    return {key: sum(1 for r in rows if test(r, today)) for key, (_, test) in STAGES.items()}


def sort_rows(rows: list[AdRow], sort: str) -> list[AdRow]:
    """Newest first by default. Unscored rows go last under either score order."""
    if sort == "oldest":
        return sorted(rows, key=lambda r: (r.captured, r.jd_id))
    if sort == "score":
        return sorted(rows, key=lambda r: (r.overall_score is None, -(r.overall_score or 0), -r.jd_id))
    if sort == "score_low":
        return sorted(rows, key=lambda r: (r.overall_score is None, r.overall_score or 0, -r.jd_id))
    if sort == "activity":
        return sorted(rows, key=lambda r: (r.last_activity, r.jd_id), reverse=True)
    return sorted(rows, key=lambda r: (r.captured, r.jd_id), reverse=True)


def _follow_up_due(r: AdRow, today: date) -> bool:
    if r.status is not S.applied:
        return False
    sent = r.applied_on or r.last_activity.date()
    return sent <= today - timedelta(days=FOLLOW_UP_DAYS)


def _verdict_matches(r: AdRow, wanted: str) -> bool:
    if not wanted:
        return True
    if wanted == "unscored":
        return r.verdict is None
    return r.verdict is not None and r.verdict.value == wanted


def _work_matches(r: AdRow, wanted: str) -> bool:
    if not wanted:
        return True
    if wanted == "contract":
        return r.work_type in (WorkType.contract, WorkType.fixed_term)
    return r.work_type is WorkType.permanent


def _one_of(value, allowed, default: str) -> str:
    return value if value in allowed else default


def ad_detail(ws: Workspace, jd_id: int, *, today: date) -> AdDetail:
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
        if jd is None:
            raise NoSuchAd(jd_id)
        assessment = store.latest_assessment(conn, jd_id)
        stale = bool(assessment) and store.latest_assessment_stale(conn, jd_id)
        seen_before = history.company_history(conn, jd)
        application = store.get_application(conn, jd_id)
        kind = store.get_role_kind(conn, jd_id)
        context = store.get_context(conn, jd_id)
    choice = masters.choose(ws, jd, kind)
    return AdDetail(
        jd=jd,
        assessment=assessment,
        stale=stale,
        history=seen_before,
        folders=outputs.documents_for(ws, jd, today),
        application=application,
        role_kind=kind,
        sent=sent.summary(ws, jd_id, today),
        context=context,
        revisable=revise.revisable(ws, jd_id, today),
        master=choice,
        masters=masters.registry(ws),
        custom=masters.advise_custom(ws, choice, assessment) if assessment else None,
    )
