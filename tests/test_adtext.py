"""Unit tests for the handling shared by every saved-ad format.

What is tested here is the part neither adapter owns: normalising the text,
finding where the advertisement starts and stops, and dropping the platform's
own furniture.
"""

from __future__ import annotations

from jobagent.adapters.adtext import (
    drop_junk,
    find_posting_metadata,
    isolate_ad,
    ExtractedAd,
    looks_truncated,
    normalise,
)


def test_collapses_ligatures() -> None:
    """A printed Seek ad comes back full of single ﬁ/ﬀ glyphs rather than the
    letter pairs. Any downstream string match against the ad fails on them
    silently — "greenﬁeld" does not contain "field"."""
    text = normalise("Conﬁdence delivering greenﬁeld projects that oﬀer scope.")

    assert text == "Confidence delivering greenfield projects that offer scope."
    assert "field" in normalise("greenﬁeld")


def test_collapses_a_non_breaking_space() -> None:
    assert normalise("Sydney NSW") == "Sydney NSW"


def test_leaves_ordinary_text_alone() -> None:
    text = "Java/Spring Boot · React — 3–6 years"

    assert normalise(text) == text


def test_an_ad_with_no_heading_still_stops_at_the_footer() -> None:
    lines = [
        "Senior IT Project Manager",
        "Our client is expanding.",
        "Be careful",
        "SEEK acknowledges the Traditional Custodians of the lands",
    ]

    assert isolate_ad(lines) == "Senior IT Project Manager\nOur client is expanding."


def test_seek_posting_line_is_found_without_a_separator() -> None:
    lines = ["IT Manager", "Posted 30d+ ago High application volume", "About the role"]

    assert find_posting_metadata(lines) == "Posted 30d+ ago High application volume"


def test_linkedin_posting_line_is_still_found() -> None:
    lines = ["Engineering Manager", "Sydney NSW·Reposted 2 weeks ago·72 applicants"]

    assert find_posting_metadata(lines) == "Sydney NSW·Reposted 2 weeks ago·72 applicants"


def test_prose_is_not_mistaken_for_a_posting_line() -> None:
    lines = ["You will own delivery · end to end · across four teams"]

    assert find_posting_metadata(lines) is None


def test_drops_platform_chrome() -> None:
    assert drop_junk(["Open app", "Show all", "IT Manager"]) == ["IT Manager"]


def test_truncation_is_only_detected_at_the_end() -> None:
    """"Show more" is ordinary furniture all over a LinkedIn page. It means the
    description was cut short only when it is the last thing in the ad."""
    assert looks_truncated("We are building the future and we… more")
    assert not looks_truncated("Show more\nWe are building the future and we ship.")


def test_a_stub_capture_is_flagged_as_thin() -> None:
    """The Mattox capture (JD 23) ended cleanly at a sentence boundary with
    565 characters and no requirements, so the '…more' guard never fired.
    Length is the signal that marker missed."""
    stub = ExtractedAd(
        text="Design and implement enterprise-scale AI solutions. " * 4,
        full_text="x" * 3138,
        source_url=None,
        page_title=None,
        posting_metadata=None,
    )

    assert len(stub.text) < 800
    assert stub.thin is True


def test_a_full_ad_is_not_thin() -> None:
    ad = ExtractedAd(
        text="w" * 800,
        full_text="x" * 9000,
        source_url=None,
        page_title=None,
        posting_metadata=None,
    )

    assert ad.thin is False
