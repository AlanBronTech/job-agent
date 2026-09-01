"""Unit tests for the application output folder."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from jobagent.adapters.docs import (
    application_folder,
    assessment_markdown,
    document_name,
    job_ad_markdown,
    write_text,
)
from jobagent.core.models import (
    ConstraintCheck,
    ConstraintStatus,
    FitAssessment,
    HiringStatus,
    JobDescription,
    MatchStatus,
    RequirementMatch,
    SalaryRange,
    Seniority,
    Verdict,
    WorkArrangement,
    WorkType,
)

WHEN = date(2026, 9, 1)


def make_jd(**overrides) -> JobDescription:
    data = {
        "id": 12,
        "title": "Engineering Manager",
        "company": "Toshiba Global Commerce Solutions (TGCS)",
        "location": "Sydney NSW",
        "work_type": WorkType.permanent,
        "work_arrangement": WorkArrangement.hybrid,
        "seniority": Seniority.manager,
        "salary_range": SalaryRange(min_aud=170000, max_aud=200000, includes_super=False),
        "must_haves": ["A strong software engineering background"],
        "nice_to_haves": ["Retail domain exposure"],
        "tech_stack": ["Kubernetes", "GitLab"],
        "responsibilities": ["Own delivery for one or more product areas"],
        "red_flags": ["No salary band provided"],
        "source": "recruiter JD document",
        "source_url": "https://example.com/jobs/1",
        "source_metadata": "Posted 26d ago",
        "raw_text": "POSITION: ENGINEERING MANAGER\nOur software runs at scale.",
        "ingested_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return JobDescription(**data)


def make_assessment(**overrides) -> FitAssessment:
    data = {
        "jd_id": 12,
        "overall_score": 62,
        "recruiter_screen_score": 50,
        "verdict": Verdict.apply_with_caveats,
        "rationale": "Genuine target-role match with a stack gap.",
        "target_role_match": True,
        "target_role_note": "Engineering Manager.",
        "constraints": [
            ConstraintCheck(
                name="salary",
                status=ConstraintStatus.unknown,
                detail="No band stated.",
                question="What is the band?",
            )
        ],
        "requirements": [
            RequirementMatch(
                requirement="Kubernetes in production",
                status=MatchStatus.gap,
                note="Absent from the profile.",
            )
        ],
        "questions_to_ask": ["What is the band?"],
        "scored_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return FitAssessment(**data)


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #


def test_the_folder_is_dated_company_and_role(tmp_path) -> None:
    folder = application_folder(tmp_path, make_jd(), when=WHEN)

    assert folder.name == "2026-09_ToshibaGlobalCommerce_EngineeringManager"
    assert folder.is_dir()


def test_an_agency_ad_falls_back_to_who_posted_it(tmp_path) -> None:
    """A blind ad has no company, and "Unknown" in the folder name for every
    agency role would make them indistinguishable."""
    jd = make_jd(company=None, posted_by="Harvey Robinson Pty Ltd", via_agency=True)

    folder = application_folder(tmp_path, jd, when=WHEN)

    assert folder.name.startswith("2026-09_HarveyRobinsonPtyLtd_")


def test_document_names_carry_company_and_month(tmp_path) -> None:
    assert document_name("Resume", make_jd(), when=WHEN) == (
        "AlanBron_Resume_ToshibaGlobalCommerce_202609.docx"
    )


def test_generating_twice_reuses_the_same_folder(tmp_path) -> None:
    first = application_folder(tmp_path, make_jd(), when=WHEN)
    again = application_folder(tmp_path, make_jd(), when=WHEN)

    assert first == again


# --------------------------------------------------------------------------- #
# The ad, kept with the documents
# --------------------------------------------------------------------------- #


def test_the_ad_keeps_the_text_the_parser_read(tmp_path) -> None:
    """Written from raw_text rather than copied from the source PDF: nothing
    records where that PDF was, and this is the text the scorer actually saw."""
    markdown = job_ad_markdown(make_jd())

    assert "POSITION: ENGINEERING MANAGER" in markdown
    assert "Our software runs at scale." in markdown


def test_the_ad_carries_what_was_parsed_out_of_it(tmp_path) -> None:
    markdown = job_ad_markdown(make_jd())

    assert "A strong software engineering background" in markdown
    assert "Retail domain exposure" in markdown
    assert "No salary band provided" in markdown
    assert "Kubernetes" in markdown
    assert "$170,000 – $200,000 + super" in markdown
    assert "https://example.com/jobs/1" in markdown
    assert "Posted 26d ago" in markdown


def test_the_ad_names_the_agency_when_there_is_one(tmp_path) -> None:
    markdown = job_ad_markdown(
        make_jd(company=None, posted_by="SustainRecruit", via_agency=True)
    )

    assert "SustainRecruit (agency)" in markdown


def test_an_ad_with_almost_nothing_parsed_still_renders(tmp_path) -> None:
    sparse = make_jd(
        company=None, location=None, salary_range=None, source=None,
        source_url=None, source_metadata=None, must_haves=[], nice_to_haves=[],
        tech_stack=[], responsibilities=[], red_flags=[],
    )

    markdown = job_ad_markdown(sparse)

    assert "Engineering Manager" in markdown
    assert "Our software runs at scale." in markdown


# --------------------------------------------------------------------------- #
# The assessment, kept with the documents
# --------------------------------------------------------------------------- #


def test_the_assessment_records_the_verdict_and_the_reasoning(tmp_path) -> None:
    markdown = assessment_markdown(make_assessment(), make_jd(), [])

    assert "apply with caveats" in markdown
    assert "62/100 hiring manager" in markdown
    assert "Genuine target-role match with a stack gap." in markdown
    assert "**BREACH**" not in markdown
    assert "**unknown**" in markdown
    assert "What is the band?" in markdown
    assert "Kubernetes in production" in markdown


def test_validation_issues_are_recorded_with_the_documents(tmp_path) -> None:
    from jobagent.core.validation import Severity, ValidationIssue

    issue = ValidationIssue(
        rule="unsupported number",
        severity=Severity.blocker,
        detail="The figure '4711' does not appear anywhere in the profile.",
        excerpt="Led 4711 engineers",
    )

    markdown = assessment_markdown(make_assessment(), make_jd(), [issue])

    assert "Validation issues raised at generation" in markdown
    assert "4711" in markdown


def test_write_text_lands_in_the_folder(tmp_path) -> None:
    folder = application_folder(tmp_path, make_jd(), when=WHEN)

    path = write_text(folder, "job-ad.md", "the ad")

    assert path.read_text(encoding="utf-8") == "the ad"
    assert path.parent == folder
