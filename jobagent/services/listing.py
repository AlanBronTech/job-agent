"""What the list and detail pages show. Read-only; costs nothing.

Everything here is already in the store or on disk. The one derived fact is
`stale`: an assessment older than the ad's last amendment was scored against
text that has since been replaced, and the free read is the one most likely
to be trusted without thinking, so it has to say so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from jobagent.adapters.document_store import OutputFolders
from jobagent.core import history, store
from jobagent.core.models import (
    Application,
    ApplicationStatus,
    CompanyHistory,
    FitAssessment,
    JobDescription,
    Verdict,
)
from jobagent.services import outputs
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


@dataclass
class AdDetail:
    jd: JobDescription
    assessment: FitAssessment | None
    stale: bool
    history: CompanyHistory
    folders: OutputFolders
    application: Application | None


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
            )
        )
    if sort == "score":
        rows.sort(
            key=lambda r: (r.overall_score is None, -(r.overall_score or 0), -r.jd_id)
        )
    return rows


def ad_detail(ws: Workspace, jd_id: int, *, today: date) -> AdDetail:
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
        if jd is None:
            raise NoSuchAd(jd_id)
        assessment = store.latest_assessment(conn, jd_id)
        stale = bool(assessment) and store.latest_assessment_stale(conn, jd_id)
        seen_before = history.company_history(conn, jd)
        application = store.get_application(conn, jd_id)
    return AdDetail(
        jd=jd,
        assessment=assessment,
        stale=stale,
        history=seen_before,
        folders=outputs.documents_for(ws, jd, today),
        application=application,
    )
