"""Unit tests for saved-web-archive extraction.

Archives are built in-test rather than committed as fixtures: Alan's real saved
pages are 5–6 MB each and contain his LinkedIn session chrome. Nothing here
touches the network — the module never fetches, by design and by hard rule.
"""

from __future__ import annotations

import quopri
from pathlib import Path

import pytest

from jobagent.adapters.mhtml import (
    MHTMLError,
    extract_ad,
    looks_like_mhtml,
)

BOUNDARY = "----MultipartBoundary--TEST----"

LINKEDIN_BODY = """
<html><head><style>.x{color:red}</style></head><body>
<nav><a>Skip to search</a><span>0 notifications</span><a>Home</a>
<a>My Network</a><a>Jobs</a><a>Messaging</a><a>Me</a></nav>
<div>Acme Corp</div>
<h1>Engineering Manager</h1>
<div>Sydney, New South Wales, Australia&middot;Reposted 2 weeks ago&middot;72 people clicked apply</div>
<div>Promoted by hirer &middot; Responses managed off LinkedIn</div>
<div>Hybrid</div><div>Full-time</div>
<div>Take the next step in your job search</div>
<div>Practice an interview</div>
<div>Applied on company site</div>
<h2>About the job</h2>
<p>You&rsquo;ll lead two squads and own delivery.</p>
<ul><li>Required: PHP and React</li><li>Desirable: AWS</li></ul>
<h2>Set alert for similar jobs</h2>
<div>People also viewed</div>
<div>Some other role at Another Company</div>
<script>var tracking = 1;</script>
</body></html>
"""


def write_archive(
    path: Path,
    body: str = LINKEDIN_BODY,
    *,
    url: str | None = "https://www.linkedin.com/jobs/view/123/",
    subject: str | None = "Engineering Manager | Acme | LinkedIn",
    charset: str = "utf-8",
) -> Path:
    """Write a minimal Chrome-style .mhtml archive."""
    encoded = quopri.encodestring(body.encode(charset)).decode("ascii")
    headers = ["From: <Saved by Blink>"]
    if url:
        headers.append(f"Snapshot-Content-Location: {url}")
    if subject:
        headers.append(f"Subject: {subject}")
    headers += [
        "MIME-Version: 1.0",
        f'Content-Type: multipart/related; type="text/html"; boundary="{BOUNDARY}"',
        "",
        f"--{BOUNDARY}",
        f"Content-Type: text/html; charset={charset}",
        "Content-Transfer-Encoding: quoted-printable",
        "",
        encoded,
        f"--{BOUNDARY}--",
        "",
    ]
    path.write_text("\r\n".join(headers), encoding=charset)
    return path


@pytest.fixture
def archive(tmp_path) -> Path:
    return write_archive(tmp_path / "job.mhtml")


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #


def test_detects_by_suffix(archive) -> None:
    assert looks_like_mhtml(archive) is True


def test_detects_by_content_when_suffix_is_wrong(tmp_path) -> None:
    odd = write_archive(tmp_path / "job.txt")

    assert looks_like_mhtml(odd) is True


def test_plain_text_is_not_an_archive(tmp_path) -> None:
    plain = tmp_path / "jd.txt"
    plain.write_text("Engineering Manager at Acme. Sydney.", encoding="utf-8")

    assert looks_like_mhtml(plain) is False


def test_missing_file_is_not_an_archive(tmp_path) -> None:
    assert looks_like_mhtml(tmp_path / "nope.txt") is False


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def test_extracts_the_advertisement(archive) -> None:
    ad = extract_ad(archive)

    assert "About the job" in ad.text
    assert "lead two squads" in ad.text
    assert "Required: PHP and React" in ad.text


def test_keeps_company_and_title_above_the_anchor(archive) -> None:
    ad = extract_ad(archive)

    assert "Acme Corp" in ad.text
    assert "Engineering Manager" in ad.text


def test_drops_navigation_chrome(archive) -> None:
    ad = extract_ad(archive)

    for junk in ("Skip to search", "My Network", "Messaging", "0 notifications"):
        assert junk not in ad.text


def test_drops_everything_after_the_advertisement(archive) -> None:
    ad = extract_ad(archive)

    assert "People also viewed" not in ad.text
    assert "Another Company" not in ad.text


def test_drops_script_and_style(archive) -> None:
    ad = extract_ad(archive)

    assert "var tracking" not in ad.text
    assert "color:red" not in ad.text


def test_smart_quotes_survive_decoding(archive) -> None:
    # Decoding with the wrong charset turns every apostrophe into U+FFFD.
    ad = extract_ad(archive)

    assert "You’ll lead two squads" in ad.text
    assert "�" not in ad.text


def test_captures_posting_metadata(archive) -> None:
    # The signal the parser kept missing: how long the ad has been live.
    ad = extract_ad(archive)

    assert ad.posting_metadata is not None
    assert "Reposted 2 weeks ago" in ad.posting_metadata
    assert "72 people clicked apply" in ad.posting_metadata


def test_captures_source_url_and_title(archive) -> None:
    ad = extract_ad(archive)

    assert ad.source_url == "https://www.linkedin.com/jobs/view/123/"
    assert ad.page_title == "Engineering Manager | Acme | LinkedIn"


def test_extraction_is_a_large_reduction(archive) -> None:
    ad = extract_ad(archive)

    assert len(ad.text) < len(ad.full_text)


# --------------------------------------------------------------------------- #
# Degrading gracefully
# --------------------------------------------------------------------------- #


def test_unknown_layout_falls_back_to_full_text(tmp_path) -> None:
    # No "About the job" anchor — a degraded parse beats refusing the file.
    body = "<html><body><h1>Some Role</h1><p>We need an engineer.</p></body></html>"
    ad = extract_ad(write_archive(tmp_path / "odd.mhtml", body))

    assert "We need an engineer." in ad.text


def test_absent_metadata_is_none_not_an_error(tmp_path) -> None:
    body = "<html><body><h2>About the job</h2><p>Lead a team.</p></body></html>"
    ad = extract_ad(write_archive(tmp_path / "bare.mhtml", body, url=None))

    assert ad.posting_metadata is None
    assert ad.source_url is None
    assert "Lead a team." in ad.text


def test_prose_containing_ago_is_not_mistaken_for_metadata(tmp_path) -> None:
    body = (
        "<html><body><h2>About the job</h2>"
        "<p>We launched a long time ago and have grown since.</p></body></html>"
    )
    ad = extract_ad(write_archive(tmp_path / "prose.mhtml", body))

    assert ad.posting_metadata is None


def test_archive_without_html_raises(tmp_path) -> None:
    path = tmp_path / "empty.mhtml"
    path.write_text(
        "From: <Saved by Blink>\r\nMIME-Version: 1.0\r\n"
        "Content-Type: text/plain\r\n\r\nnot html\r\n",
        encoding="utf-8",
    )

    with pytest.raises(MHTMLError, match="no HTML part"):
        extract_ad(path)


def test_unreadable_file_raises(tmp_path) -> None:
    with pytest.raises(MHTMLError, match="Could not read"):
        extract_ad(tmp_path / "does_not_exist.mhtml")
