"""An email saved as PDF is not a job link: Gmail's footer address is every email's."""

from __future__ import annotations

from datetime import datetime, timezone

from jobagent.adapters.adtext import is_mailbox_url
from jobagent.adapters.pdf import _source_url
from jobagent.core import store
from jobagent.core.models import JobDescription, WorkArrangement, WorkType
from jobagent.services.ads import AdInput, already_stored

GMAIL = "https://mail.google.com/mail/u/0"


def test_mailbox_urls():
    assert is_mailbox_url(GMAIL)
    assert is_mailbox_url("https://outlook.office.com/mail/inbox")
    assert not is_mailbox_url("https://www.seek.com.au/job/12345")
    assert not is_mailbox_url(None)


def test_a_pdf_printed_from_gmail_has_no_source_url():
    assert _source_url([GMAIL, GMAIL]) is None
    assert _source_url(["https://jobs.example.invalid/42"]) == "https://jobs.example.invalid/42"


def test_two_emails_from_gmail_are_not_the_same_ad(tmp_path):
    with store.open_store(tmp_path / "db") as conn:
        store.add_jd(conn, JobDescription(
            title="Engineering Manager", company="Northwind Freight", work_type=WorkType.permanent,
            work_arrangement=WorkArrangement.hybrid, raw_text="First recruiter email. " * 20,
            source_url=GMAIL, source_file="Gmail - First.pdf",
            ingested_at=datetime(2026, 10, 19, tzinfo=timezone.utc)))
        second = AdInput(raw_text="Second recruiter email. " * 20, source_url=GMAIL,
                         name="Gmail - Second.pdf")
        assert already_stored(conn, second) is None
