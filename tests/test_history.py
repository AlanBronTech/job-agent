"""Unit tests for company history. No LLM, no network.

The case behind this file: Nuix screened Alan out on JD 14, then posted a
different role in the same team the next day. `jd add` said nothing, and the
next command he would have run costs $0.20.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from jobagent.core import history, store
from jobagent.core.models import (
    Application,
    ApplicationStatus,
    JobDescription,
    Worth,
    WorkArrangement,
    WorkType,
)

NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    connection = store.connect(":memory:")
    yield connection
    connection.close()


def make_jd(
    title: str = "Engineering Manager",
    company: str | None = "Nuix",
    *,
    source_url: str | None = None,
    days_ago: int = 0,
) -> JobDescription:
    return JobDescription(
        title=title,
        company=company,
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        source_url=source_url,
        raw_text="We are hiring an Engineering Manager. " * 40,
        ingested_at=NOW - timedelta(days=days_ago),
    )


def add(conn, jd: JobDescription, status: ApplicationStatus | None = None, **kwargs) -> int:
    jd_id = store.add_jd(conn, jd)
    if status is not None:
        store.save_application(
            conn,
            Application(jd_id=jd_id, status=status, updated_at=NOW, **kwargs),
        )
    return jd_id


# --------------------------------------------------------------------------- #
# Which names are one employer
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Nuix", "nuix"),
        ("Nuix Pty Ltd", "nuix"),
        ("The Onset", "onset"),
        ("Toshiba Global Commerce Solutions (TGCS)", "toshiba global commerce solutions"),
        ("United Fasteners Australia Pty Ltd", "united fasteners australia"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalise_company(name, expected) -> None:
    assert history.normalise_company(name) == expected


@pytest.mark.parametrize(
    "left, right",
    [
        ("Nuix", "Nuix"),
        ("Nuix", "nuix pty ltd"),
        ("Nuix", "Nuix Technologies"),
        ("The Onset", "Onset"),
    ],
)
def test_the_same_employer_written_two_ways(left, right) -> None:
    assert history.same_company(left, right)


@pytest.mark.parametrize(
    "left, right",
    [
        ("Nuix", "Xero"),
        ("Nuix", None),
        ("Nuix", ""),
        # Not a prefix, so not a match — an employer whose name merely ends the
        # same way is a different employer.
        ("Global Nuix", "Nuix"),
    ],
)
def test_different_employers(left, right) -> None:
    assert not history.same_company(left, right)


# --------------------------------------------------------------------------- #
# What the store knows
# --------------------------------------------------------------------------- #


def test_no_history_is_no_warning(conn) -> None:
    jd = make_jd()
    jd.id = add(conn, jd)

    assert not history.company_history(conn, jd)


def test_an_ad_never_matches_itself(conn) -> None:
    jd = make_jd()
    jd.id = add(conn, jd)

    assert history.company_history(conn, jd).encounters == []


def test_an_ad_with_no_company_has_no_history(conn) -> None:
    """Matching on title alone would put every Engineering Manager on one
    warning. A blind agency ad names no company and gets nothing."""
    add(conn, make_jd(company="Nuix", days_ago=1))
    jd = make_jd(company=None)
    jd.id = add(conn, jd)

    assert not history.company_history(conn, jd)


def test_a_prior_rejection_is_reported(conn) -> None:
    add(
        conn,
        make_jd("Engineering Manager - AI Team", days_ago=1),
        ApplicationStatus.rejected_screen,
        worth_applying=Worth.yes,
        worth_why="I fit the job description reasonably well.",
    )
    jd = make_jd("Principal Software Engineer - AI Team")
    jd.id = add(conn, jd)

    seen = history.company_history(conn, jd)

    assert seen.company == "Nuix"
    assert [e.title for e in seen.encounters] == ["Engineering Manager - AI Team"]
    assert len(seen.rejections) == 1
    assert seen.rejections[0].worth_why.startswith("I fit")
    assert seen.applications == seen.encounters


def test_an_ingested_ad_never_applied_to_still_counts(conn) -> None:
    """Any prior contact warns, not only applications."""
    add(conn, make_jd(days_ago=2))
    jd = make_jd("Principal Software Engineer")
    jd.id = add(conn, jd)

    seen = history.company_history(conn, jd)

    assert len(seen.encounters) == 1
    assert seen.encounters[0].status is None
    assert seen.applications == []


def test_identified_is_not_an_application(conn) -> None:
    add(conn, make_jd(days_ago=2), ApplicationStatus.identified)
    jd = make_jd("Principal Software Engineer")
    jd.id = add(conn, jd)

    assert history.company_history(conn, jd).applications == []


def test_the_same_posting_is_called_out(conn) -> None:
    """Four of the first twenty-four rows are one ad ingested repeatedly."""
    url = "https://www.linkedin.com/jobs/view/4442591733/"
    add(conn, make_jd(source_url=url, days_ago=1))
    jd = make_jd(source_url=url.rstrip("/"))
    jd.id = add(conn, jd)

    seen = history.company_history(conn, jd)

    assert len(seen.same_posting) == 1


def test_a_different_posting_is_not(conn) -> None:
    add(conn, make_jd(source_url="https://example.com/jobs/1", days_ago=1))
    jd = make_jd(source_url="https://example.com/jobs/2")
    jd.id = add(conn, jd)

    assert history.company_history(conn, jd).same_posting == []


def test_encounters_are_newest_first(conn) -> None:
    add(conn, make_jd("Oldest", days_ago=5))
    add(conn, make_jd("Newest", days_ago=1))
    add(conn, make_jd("Middle", days_ago=3))
    jd = make_jd("This one")
    jd.id = add(conn, jd)

    seen = history.company_history(conn, jd)

    assert [e.title for e in seen.encounters] == ["Newest", "Middle", "Oldest"]


def test_other_companies_are_left_out(conn) -> None:
    add(conn, make_jd(company="Xero", days_ago=1), ApplicationStatus.rejected_screen)
    jd = make_jd(company="Nuix")
    jd.id = add(conn, jd)

    assert not history.company_history(conn, jd)
