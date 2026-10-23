"""Reading job-alert emails: from Gmail over IMAP, or from saved .eml files.

Read-only by construction. Folders are opened with `readonly=True` and bodies
fetched with BODY.PEEK, so nothing is marked read, moved or deleted. Standard
library only (`imaplib`, `email`): a Gmail app password in `.env` is the whole
setup, with no Google client library or OAuth flow to maintain.

Only the alert emails are read. The search names SEEK's and LinkedIn's
senders, and nothing here follows a link found in a message (CLAUDE.md, hard
rule 1).
"""

from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

GMAIL_IMAP = "imap.gmail.com"
SENDERS = ("seek.com.au", "linkedin.com")
# Alan reads an alert and bins it, so the bin is searched as well as the
# archive. Found by the folders' special-use flags, because Gmail names them
# by locale: "[Gmail]/Trash" in the US, "[Gmail]/Bin" in Australia.
_WANTED_FLAGS = (r"\All", r"\Trash")


class MailboxError(Exception):
    """The mailbox could not be read."""


@dataclass(frozen=True)
class Mail:
    message_id: str
    sender: str
    subject: str
    received: datetime
    text: str


def fetch_gmail(address: str, app_password: str, since: date, *, host: str = GMAIL_IMAP) -> list[Mail]:
    """Every SEEK or LinkedIn email since `since`, from All Mail and the bin."""
    try:
        conn = imaplib.IMAP4_SSL(host)
    except OSError as exc:
        raise MailboxError(f"Could not reach {host}: {exc}") from exc
    try:
        try:
            conn.login(address, app_password)
        except imaplib.IMAP4.error as exc:
            raise MailboxError(
                "Gmail refused the login. Use an app password (Google Account → Security → "
                f"App passwords), not your normal password. ({exc})"
            ) from exc
        found: dict[str, Mail] = {}
        for folder in _folders(conn):
            status, _ = conn.select(_quote(folder), readonly=True)
            if status != "OK":
                continue
            for mail in _search(conn, since):
                found.setdefault(mail.message_id, mail)
        return sorted(found.values(), key=lambda m: m.received)
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 - closing a connection that already failed
            pass


def read_eml_dir(folder: Path, since: date | None = None) -> list[Mail]:
    """Alert emails saved as .eml files ("Download message" in Gmail)."""
    mails = []
    for path in sorted(folder.glob("*.eml")):
        mail = to_mail(path.read_bytes())
        if mail and (since is None or mail.received.date() >= since):
            mails.append(mail)
    return mails


def to_mail(raw: bytes) -> Mail | None:
    """A parsed message, if it came from SEEK or LinkedIn."""
    message = email.message_from_bytes(raw, policy=policy.default)
    sender = str(message.get("From", ""))
    if not any(s in sender.lower() for s in SENDERS):
        return None
    try:
        received = parsedate_to_datetime(str(message.get("Date")))
    except (TypeError, ValueError):
        received = datetime.now(timezone.utc)
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    return Mail(
        message_id=str(message.get("Message-ID", "")) or f"{sender}|{received.isoformat()}",
        sender=sender,
        subject=str(message.get("Subject", "")),
        received=received,
        text=text_of(message),
    )


def text_of(message: EmailMessage) -> str:
    """The plain-text part; failing that, the HTML part reduced to lines."""
    plain = message.get_body(preferencelist=("plain",))
    if plain is not None:
        return plain.get_content()
    html_part = message.get_body(preferencelist=("html",))
    return _html_to_text(html_part.get_content()) if html_part is not None else ""


# --------------------------------------------------------------------------- #


def _folders(conn: imaplib.IMAP4) -> list[str]:
    status, rows = conn.list()
    if status != "OK":
        raise MailboxError("Could not list the mailbox folders.")
    names = []
    for row in rows or []:
        line = row.decode(errors="replace") if isinstance(row, bytes) else str(row)
        match = re.match(r'\((?P<flags>[^)]*)\) "(?P<sep>[^"]*)" (?P<name>.+)$', line)
        if match and any(flag in match["flags"] for flag in _WANTED_FLAGS):
            names.append(match["name"].strip().strip('"'))
    return names or ["INBOX"]


def _quote(folder: str) -> str:
    return f'"{folder}"'


def _search(conn: imaplib.IMAP4, since: date) -> list[Mail]:
    criteria = " ".join(["OR"] * (len(SENDERS) - 1) + [f'FROM "{s}"' for s in SENDERS])
    status, data = conn.search(None, f'(SINCE {since:%d-%b-%Y} {criteria})')
    if status != "OK" or not data or not data[0]:
        return []
    mails = []
    for number in data[0].split():
        status, parts = conn.fetch(number, "(BODY.PEEK[])")
        if status != "OK":
            continue
        raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
        mail = to_mail(raw) if raw else None
        if mail:
            mails.append(mail)
    return mails


class _Text(HTMLParser):
    _BREAKS = {"br", "p", "div", "tr", "td", "li", "h1", "h2", "h3", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._BREAKS:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.parts.append(f"\n[{href}]\n")

    def handle_data(self, data):
        self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(lines)
