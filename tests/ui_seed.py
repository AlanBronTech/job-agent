"""Invented ads for the UI tests. Every company, figure and person is made up.

    1  Northwind Freight  Platform Lead           not scored; rejected_screen
    2  Northwind Freight  Engineering Manager     skip 41/35, salary floor breach
    3  Acme Logistics     Engineering Manager     apply 78/70, one "not stated"
    4  Contoso Health     Head of Engineering     not scored
    5  Fabrikam Energy    Delivery Manager        apply_with_caveats 60/55, then amended
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from jobagent.adapters.document_store import LocalFolderStore
from jobagent.core import store
from jobagent.core.models import (
    Application,
    ApplicationStatus,
    ChallengePoint,
    ConstraintCheck,
    ConstraintStatus,
    FitAssessment,
    JobDescription,
    MatchStatus,
    RequirementMatch,
    Verdict,
    WorkArrangement,
    WorkType,
)
from jobagent.services.workspace import Workspace

T0 = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 29)


def workspace(tmp_path) -> Workspace:
    return Workspace(
        owner="local",
        profile_dir=None,
        db_path=tmp_path / "jobagent.db",
        runs_log_path=tmp_path / "runs.jsonl",
        jd_dir=tmp_path / "jds",
        documents=LocalFolderStore(tmp_path / "out"),
    )


def jd(title: str, company: str, day: int, **extra) -> JobDescription:
    return JobDescription(
        title=title,
        company=company,
        location="Sydney NSW",
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        raw_text=f"{title} at {company}. An invented advertisement. " * 30,
        ingested_at=T0 + timedelta(days=day),
        **extra,
    )


def assessment(jd_id: int, verdict: Verdict, overall: int, screen: int, **extra) -> FitAssessment:
    return FitAssessment(
        jd_id=jd_id,
        overall_score=overall,
        recruiter_screen_score=screen,
        verdict=verdict,
        rationale=f"Invented rationale for JD {jd_id}.",
        target_role_match=True,
        target_role_note="An engineering leadership role.",
        model_used="test-model",
        scored_at=T0 + timedelta(days=20),
        **extra,
    )


def seed(ws: Workspace) -> dict[str, int]:
    ids = {}
    with store.open_store(ws.db_path) as conn:
        ids["northwind_old"] = store.add_jd(conn, jd("Platform Lead", "Northwind Freight", 0))
        store.save_application(
            conn,
            Application(
                jd_id=ids["northwind_old"],
                status=ApplicationStatus.rejected_screen,
                updated_at=T0,
            ),
        )
        ids["northwind"] = store.add_jd(
            conn, jd("Engineering Manager", "Northwind Freight", 5)
        )
        store.add_assessment(
            conn,
            assessment(
                ids["northwind"],
                Verdict.skip,
                41,
                35,
                constraints=[
                    ConstraintCheck(
                        name="salary floor",
                        status=ConstraintStatus.breach,
                        detail="Advertised top of band is below the floor.",
                    )
                ],
            ),
        )
        ids["acme"] = store.add_jd(
            conn,
            jd(
                "Engineering Manager",
                "Acme Logistics",
                10,
                source_url="https://jobs.example.invalid/acme-em",
            ),
        )
        store.add_assessment(
            conn,
            assessment(
                ids["acme"],
                Verdict.apply,
                78,
                70,
                constraints=[
                    ConstraintCheck(name="employment type", status=ConstraintStatus.ok, detail="Permanent."),
                    ConstraintCheck(
                        name="office location",
                        status=ConstraintStatus.unknown,
                        detail="The ad names no suburb.",
                        question="Which office would the role sit in?",
                    ),
                ],
                requirements=[
                    RequirementMatch(
                        requirement="Led teams of eight or more",
                        status=MatchStatus.met,
                        evidence_ref="role_example.1",
                        note="Invented evidence.",
                    ),
                    RequirementMatch(
                        requirement="Kubernetes in production",
                        status=MatchStatus.gap,
                        note="Not in the profile.",
                    ),
                ],
                challenge_points=[
                    ChallengePoint(point="No logistics domain.", response="Invented response.")
                ],
                questions_to_ask=["How large is the platform team?"],
            ),
        )
        ids["contoso"] = store.add_jd(conn, jd("Head of Engineering", "Contoso Health", 15))
        ids["fabrikam"] = store.add_jd(conn, jd("Delivery Manager", "Fabrikam Energy", 12))
        store.add_assessment(
            conn, assessment(ids["fabrikam"], Verdict.apply_with_caveats, 60, 55)
        )
        amended = jd("Delivery Manager", "Fabrikam Energy", 12)
        amended.raw_text += " The full description arrived later."
        store.update_jd(conn, ids["fabrikam"], amended, amended_at=T0 + timedelta(days=25))
    return ids
