"""Requisition numbers read from ad text: exact, never guessed. Invented ads."""

from __future__ import annotations

import pytest

from jobagent.core.requisition import (
    extract_requisition,
    normalise_requisition,
    requisition_candidates,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Engineering Manager — JR_000123 — Sydney", "JR_000123"),
        ("Apply by Friday. Requisition: JR-004567.", "JR-004567"),
        ("Req ID: 45871. Hybrid, Sydney.", "45871"),
        ("Req ID 45871", "45871"),
        ("Job reference: ABC-2026-77", "ABC-2026-77"),
        ("Reference number: REF2026/15", "REF2026/15"),
        ("Job No. A-9912 closes soon", "A-9912"),
        ("Vacancy #88231", "88231"),
    ],
)
def test_extracts_exactly_as_written(text, expected):
    assert extract_requisition(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "We are hiring an Engineering Manager in Sydney.",
        "Job type: Permanent. Position: Engineering Manager.",
        "References available on request.",
        "Reference: available on request",
        "Over 100 applicants. Reposted 1 week ago.",
        "",
    ],
)
def test_none_when_there_is_no_number(text):
    assert extract_requisition(text) is None


def test_two_different_numbers_give_none():
    text = "Role JR_000123. Similar role: JR_000456."
    assert requisition_candidates(text) == ["JR_000123", "JR_000456"]
    assert extract_requisition(text) is None


def test_the_same_number_twice_is_one():
    assert extract_requisition("JR_000123 … quote JR-000123 when applying") == "JR_000123"


def test_normalised_form_matches_across_spellings():
    assert normalise_requisition("JR_000123") == normalise_requisition("jr-000123") == "JR000123"
