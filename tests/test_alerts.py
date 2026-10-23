"""Job-alert emails: parsing, the filter, dedup against the pipeline, decisions. Invented data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.adapters import mailbox
from jobagent.core import alerts as core
from jobagent.core import store
from jobagent.core.models import AlertDecision, AlertRules, AlertVerdict
from jobagent.services import alerts
from jobagent.services.workspace import Workspace
from tests.ui_seed import jd, workspace

FIXTURES = Path(__file__).parent / "fixtures" / "alerts"
SEEK_TEXT = (FIXTURES / "seek.txt").read_text()
LINKEDIN_TEXT = (FIXTURES / "linkedin.txt").read_text()
NOW = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)
RULES = AlertRules(
    want_titles=["engineering manager", "delivery manager", "engineering lead"],
    maybe_titles=["tech lead", "team lead"],
    contract_titles=["software engineer", "programmer"],
    never_titles=["network", "roads", "data scientist"],
)
runner = CliRunner()


def mail(sender, text, *, subject="New jobs", when=NOW, mid=None):
    return mailbox.Mail(message_id=mid or f"{sender}-{when}", sender=sender, subject=subject,
                        received=when, text=text)


# -- parsing ------------------------------------------------------------------


def test_seek_listings_are_read_back_from_each_link():
    got = {l.job_id: l for l in core.parse_seek(SEEK_TEXT)}
    assert list(got) == [f"9000000{i}" for i in range(1, 7)]
    first = got["90000001"]
    assert (first.title, first.company, first.location, first.pay) == (
        "Engineering Manager, Payments Platform", "Contoso", "Sydney NSW", "World Class Benefits")
    assert got["90000002"].pay == "$180k - $195k + Super"
    assert got["90000005"].title == "Tech Lead"  # SEEK glues its "New" badge on
    missed = got["90000006"]  # from "Jobs you may have missed", after the email's own headings
    assert (missed.title, missed.company, missed.pay) == (
        "Senior Software Engineer", "Adatum Recruitment", "Day rate up to $1,000")
    assert first.url == "https://au.seek.com/job/90000001"


def test_linkedin_listings_including_the_insights_layout():
    got = {l.job_id: l for l in core.parse_linkedin(LINKEDIN_TEXT)}
    assert list(got) == ["4000000001", "4000000002", "4000000003", "4000000004"]
    assert (got["4000000001"].title, got["4000000001"].company, got["4000000001"].location) == (
        "Engineering Team Lead - Experience Platform", "Woodgrove", "Sydney, NSW")
    assert got["4000000002"].company == "Proseware Civil"  # a badge after a blank line is dropped
    assert (got["4000000004"].company, got["4000000004"].location) == ("Lucerne", "Sydney, NSW")
    assert got["4000000003"].url == "https://www.linkedin.com/jobs/view/4000000003/"


def test_parse_email_dispatches_on_the_sender():
    assert core.parse_email("SEEK <jobmail@s.seek.com.au>", SEEK_TEXT)
    assert core.parse_email("LinkedIn <jobalerts-noreply@linkedin.com>", LINKEDIN_TEXT)
    assert core.parse_email("someone@example.com", SEEK_TEXT) == []


def test_job_key_reads_stored_ad_urls():
    assert core.job_key("https://au.seek.com/job/95400631") == ("seek", "95400631")
    assert core.job_key("https://www.seek.com.au/job/95400631?x=1") == ("seek", "95400631")
    assert core.job_key("https://www.linkedin.com/jobs/view/4471179266") == ("linkedin", "4471179266")
    assert core.job_key("https://mail.google.com/mail/u/0") is None


# -- pay and the filter ---------------------------------------------------------


@pytest.mark.parametrize("text, amount, daily", [
    ("$180k - $195k + Super", 195_000, False),
    ("165-175k+ SUPER", 175_000, False),
    ("$133348.0k - $146945.0k p.a.", 146_945, False),
    ("200000", 200_000, False),
    ("$950 per day incl. super", 950, True),
    ("Up to $1100 p.d.", 1100, True),
    ("Syd, Onsite,12M Contract-Extend-$800-$1100 Ped Day", 1100, True),
    ("$200,000 – $220,000 per year Plus 20% bonus", 220_000, False),
])
def test_read_pay_takes_the_top_of_the_band(text, amount, daily):
    assert core.read_pay(text) == core.Pay(amount, daily)


@pytest.mark.parametrize("text", ["", "World Class Benefits", "Salary packaging + Laptop", "Competitive"])
def test_no_figure_is_no_pay(text):
    assert core.read_pay(text) is None


def judge(title, pay=""):
    listing = core.Listing("seek", "1", title, "Co", "Sydney NSW", pay)
    return core.judge(listing, RULES, min_salary=150_000, min_day_rate=800)


def test_the_filter():
    assert judge("Engineering Manager, Payments").verdict is AlertVerdict.suggest
    assert judge("Network Engineering Manager").reason == "title: network"  # never wins
    assert judge("Tech Lead").verdict is AlertVerdict.maybe
    assert judge("Delivery Manager", "$110k - $120k").reason.startswith("pay up to $120,000")
    assert judge("Senior Software Engineer", "Day rate up to $1,000").verdict is AlertVerdict.maybe
    assert judge("Senior Software Engineer").reason.startswith("hands-on role with no day rate")
    assert judge("Senior Software Engineer", "$700 per day").reason.startswith("day rate up to $700")
    assert judge("Barista").reason == "title is not a target role"
    assert judge("Engineering Lead").verdict is AlertVerdict.suggest  # whole words, not "lead" alone


# -- the service ------------------------------------------------------------------


@pytest.fixture
def ws(tmp_path, monkeypatch):
    w = workspace(tmp_path)
    monkeypatch.setattr(alerts, "_rules", lambda ws: RULES)
    monkeypatch.setattr(alerts, "_filters", lambda ws: (150_000, 800))
    return w


def test_ingest_dedupes_suggests_and_skips(ws):
    result = alerts.ingest(ws, [
        mail("jobmail@s.seek.com.au", SEEK_TEXT),
        mail("jobalerts-noreply@linkedin.com", LINKEDIN_TEXT),
        mail("jobmail@s.seek.com.au", SEEK_TEXT, when=NOW + timedelta(hours=1), mid="again"),
    ], now=NOW)
    assert (result.emails, result.listings, result.new) == (3, 16, 10)
    by_title = {}
    for row in alerts.listings(ws):
        by_title.setdefault(row.title, []).append(row)
    contoso = by_title["Engineering Manager, Payments Platform"]
    # The same job on SEEK and LinkedIn is suggested once.
    assert sorted(r.verdict.value for r in contoso) == ["skip", "suggest"]
    assert any(r.reason.startswith("same job as listing") for r in contoso)
    seek_row = next(r for r in contoso if r.source == "seek")
    assert seek_row.times_seen == 2
    items = alerts.pending(ws, NOW)
    pending = [p.listing.title for p in items]
    # Suggestions before maybes.
    verdicts = [p.listing.verdict for p in items]
    assert verdicts == sorted(verdicts, key=lambda v: v is not AlertVerdict.suggest)
    assert {"Engineering Manager, Payments Platform", "Delivery Manager",
            "Engineering Team Lead - Experience Platform", "Tech Lead"} <= set(pending)
    assert "Network Engineering Manager" not in pending and "Senior Programmer" not in pending
    assert "Senior Software Engineer" in pending  # contract at $1,000/day


def test_an_ad_already_in_jobagent_is_not_suggested(ws):
    with store.open_store(ws.db_path) as conn:
        ad = jd("Delivery Manager", "Fabrikam Digital", 0)
        ad.source_url = "https://au.seek.com/job/90000002"
        jd_id = store.add_jd(conn, ad)
    alerts.ingest(ws, [mail("jobmail@s.seek.com.au", SEEK_TEXT)], now=NOW)
    row = next(r for r in alerts.listings(ws) if r.job_id == "90000002")
    assert row.verdict is AlertVerdict.skip and row.reason == f"already in JobAgent as JD {jd_id}"
    assert row.jd_id == jd_id


def test_decisions_take_listings_off_the_list_and_later_keeps_them(ws):
    alerts.ingest(ws, [mail("jobmail@s.seek.com.au", SEEK_TEXT)], now=NOW)
    by_job = {p.listing.job_id: p.listing.id for p in alerts.pending(ws, NOW)}
    first, second = by_job["90000001"], by_job["90000002"]
    alerts.decide(ws, [first], AlertDecision.not_relevant, note="civil, not software", now=NOW)
    alerts.decide(ws, [second], AlertDecision.later, now=NOW)
    ids = [p.listing.id for p in alerts.pending(ws, NOW)]
    assert first not in ids and second in ids
    with pytest.raises(alerts.NoSuchListing):
        alerts.decide(ws, [second, 999], AlertDecision.saved, now=NOW)
    assert store.get_alert(store.connect(ws.db_path), second).decision is AlertDecision.later
    report = alerts.report(ws)
    assert [r.id for r in report.not_relevant] == [first]
    # A repost with a new id is not suggested again once decided.
    repost = SEEK_TEXT.replace("90000001", "90000099")
    alerts.ingest(ws, [mail("jobmail@s.seek.com.au", repost, mid="repost")], now=NOW)
    row = next(r for r in alerts.listings(ws) if r.job_id == "90000099")
    assert row.reason == f"decided before as not_relevant (listing {first})"


def test_stale_listings_drop_off(ws):
    alerts.ingest(ws, [mail("jobmail@s.seek.com.au", SEEK_TEXT, when=NOW - timedelta(days=30))], now=NOW)
    assert alerts.pending(ws, NOW) == []


def test_saving_the_ad_marks_the_listing_saved(ws):
    alerts.ingest(ws, [mail("jobmail@s.seek.com.au", SEEK_TEXT)], now=NOW)
    ad = jd("Delivery Manager", "Fabrikam Digital", 0)
    ad.source_url = "https://au.seek.com/job/90000002?x=1"
    with store.open_store(ws.db_path) as conn:
        ad.id = store.add_jd(conn, ad)
    row = alerts.link_ad(ws, ad, NOW)
    assert row.decision is AlertDecision.saved and row.jd_id == ad.id


def test_an_alert_email_that_yields_nothing_is_reported(ws):
    result = alerts.ingest(ws, [mail("jobmail@s.seek.com.au", "a layout we cannot read https://au.seek.com/job/1",
                                     subject="20 new jobs for engineering manager")], now=NOW)
    assert result.unread == ["20 new jobs for engineering manager"]


def test_default_since_is_the_day_before_the_last_fetch(ws):
    assert alerts.default_since(ws, NOW.date()) == NOW.date() - timedelta(days=7)
    alerts.ingest(ws, [], now=NOW)
    assert alerts.default_since(ws, NOW.date()) == NOW.date() - timedelta(days=1)


# -- the mailbox adapter, offline ---------------------------------------------------


def test_eml_files_are_read_and_other_senders_ignored(tmp_path):
    for name, sender, body in (("a.eml", "SEEK <jobmail@s.seek.com.au>", SEEK_TEXT),
                               ("b.eml", "friend@example.com", "hello")):
        msg = EmailMessage()
        msg["From"], msg["Subject"] = sender, "x"
        msg["Date"] = "Thu, 22 Oct 2026 23:44:30 +0000"
        msg["Message-ID"] = f"<{name}@test>"
        msg.set_content(body)
        (tmp_path / name).write_bytes(bytes(msg))
    mails = mailbox.read_eml_dir(tmp_path)
    assert [m.sender for m in mails] == ["SEEK <jobmail@s.seek.com.au>"]
    assert core.parse_email(mails[0].sender, mails[0].text)


def test_an_html_only_email_is_reduced_to_lines():
    msg = EmailMessage()
    msg["From"] = "jobmail@s.seek.com.au"
    msg.set_content('<div>Delivery Manager</div><div>Fabrikam</div><div>Sydney NSW</div>'
                    '<a href="https://au.seek.com/job/90000002?x">View</a>', subtype="html")
    text = mailbox.text_of(msg)
    assert [l.job_id for l in core.parse_seek(text)] == ["90000002"]


# -- the CLI --------------------------------------------------------------------------


def test_cli_fetch_from_a_folder_list_and_decide(tmp_path, monkeypatch):
    from jobagent.cli import alerts as cli
    from jobagent.cli.main import app

    ws = workspace(tmp_path)
    monkeypatch.setattr(cli, "_ws", lambda: ws)
    monkeypatch.setattr(alerts, "_rules", lambda w: RULES)
    monkeypatch.setattr(alerts, "_filters", lambda w: (150_000, 800))
    folder = tmp_path / "eml"
    folder.mkdir()
    msg = EmailMessage()
    msg["From"], msg["Subject"] = "jobmail@s.seek.com.au", "5 new jobs"
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.set_content(SEEK_TEXT)
    (folder / "a.eml").write_bytes(bytes(msg))

    result = runner.invoke(app, ["alerts", "fetch", "--dir", str(folder), "--since", "2026-01-01"])
    assert result.exit_code == 0, result.output
    assert "Read 1 alert email(s)" in result.output
    listed = runner.invoke(app, ["alerts", "list"])
    assert "Worth a look" in listed.output and "https://au.seek.com/job/90000001" in listed.output
    decided = runner.invoke(app, ["alerts", "decide", "nq", "1", "--note", "needs Go"])
    assert decided.exit_code == 0 and "not_qualified" in decided.output
    assert runner.invoke(app, ["alerts", "decide", "maybe", "1"]).exit_code == 2
    assert runner.invoke(app, ["alerts", "decide", "s", "999"]).exit_code == 1
    assert "Not qualified" in runner.invoke(app, ["alerts", "report"]).output


def test_gmail_is_read_read_only_from_all_mail_and_the_bin(monkeypatch):
    msg = EmailMessage()
    msg["From"], msg["Subject"] = "SEEK <jobmail@s.seek.com.au>", "5 new jobs"
    msg["Date"], msg["Message-ID"] = "Thu, 22 Oct 2026 23:44:30 +0000", "<one@seek>"
    msg.set_content(SEEK_TEXT)
    raw = bytes(msg)
    calls = []

    class FakeIMAP:
        def __init__(self, host):
            calls.append(("connect", host))

        def login(self, user, password):
            calls.append(("login", user))

        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                          b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
                          b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Bin"']

        def select(self, folder, readonly=False):
            calls.append(("select", folder, readonly))
            return "OK", [b"1"]

        def search(self, charset, criteria):
            calls.append(("search", criteria))
            return "OK", [b"1"]

        def fetch(self, number, what):
            calls.append(("fetch", what))
            return "OK", [(b"1 (BODY[] {n}", raw), b")"]

        def logout(self):
            calls.append(("logout",))

    monkeypatch.setattr(mailbox.imaplib, "IMAP4_SSL", FakeIMAP)
    mails = mailbox.fetch_gmail("me@example.com", "app-pass", datetime(2026, 10, 20).date())
    assert len(mails) == 1  # the same message in both folders counts once
    selects = [c for c in calls if c[0] == "select"]
    assert selects == [("select", '"[Gmail]/All Mail"', True), ("select", '"[Gmail]/Bin"', True)]
    assert all(c[1] == "(BODY.PEEK[])" for c in calls if c[0] == "fetch")
    assert any("SINCE 20-Oct-2026" in c[1] and 'FROM "seek.com.au"' in c[1] for c in calls if c[0] == "search")
    assert calls[-1] == ("logout",)



def test_a_first_listing_without_a_logo_does_not_take_the_greeting_as_its_title():
    text = (
        "Hi Alex,\nBased on your saved search for software development manager in All Sydney NSW,\n"
        "we\u2019ve found 19 new jobs that could be right for you.\n\nDelivery Manager\nFabrikam Digital\n\n"
        "Mascot, Sydney NSW\n$180k - $195k + Super\n\n[https://au.seek.com/job/90000002?x=1]\n"
    )
    [listing] = core.parse_seek(text)
    assert (listing.title, listing.company, listing.pay) == ("Delivery Manager", "Fabrikam Digital", "$180k - $195k + Super")


def test_an_email_with_no_job_links_is_not_reported_as_unreadable(ws):
    result = alerts.ingest(ws, [mail("jobs-noreply@linkedin.com", "Find the right job for you on LinkedIn",
                                     subject="Alan, looking for a new job?")], now=NOW)
    assert result.unread == []


def test_reading_the_same_email_twice_does_not_count_it_twice(ws):
    m = mail("jobmail@s.seek.com.au", SEEK_TEXT, mid="<same@seek>")
    alerts.ingest(ws, [m], now=NOW)
    alerts.ingest(ws, [m], now=NOW + timedelta(minutes=5))
    assert {r.times_seen for r in alerts.listings(ws)} == {1}
