"""Moving an application folder aside instead of overwriting it.

No network, no cost. Invented company throughout.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone

import pytest

from jobagent.adapters import docs
from jobagent.core.models import JobDescription, WorkArrangement, WorkType

NOW = datetime(2026, 9, 29, 14, 5, 12)


def make_jd() -> JobDescription:
    return JobDescription(
        title="Engineering Manager",
        company="Acme Logistics",
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        raw_text="An invented ad. " * 40,
        ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def folder(tmp_path):
    jd = make_jd()
    path = docs.application_folder(tmp_path, jd, when=date(2026, 9, 29))
    (path / "AlanBron_Resume_AcmeLogistics_202609.docx").write_bytes(b"edited by hand")
    return path


def test_name_keeps_suffix_and_carries_timestamp(folder):
    moved = docs.supersede_folder(folder, NOW)
    assert moved.name == (
        "2026-09.superseded-20260929T140512_AcmeLogistics_EngineeringManager"
    )
    assert moved.parent == folder.parent
    assert not folder.exists()
    assert (moved / "AlanBron_Resume_AcmeLogistics_202609.docx").read_bytes() == (
        b"edited by hand"
    )


def test_superseded_folder_is_still_found_for_the_ad(folder, tmp_path):
    moved = docs.supersede_folder(folder, NOW)
    found = docs.folders_for(tmp_path, make_jd())
    assert moved in found


def test_is_superseded(folder):
    assert not docs.is_superseded(folder)
    assert docs.is_superseded(docs.supersede_folder(folder, NOW))


def test_existing_target_refuses_and_leaves_folder_untouched(folder):
    target = folder.parent / (
        "2026-09.superseded-20260929T140512_AcmeLogistics_EngineeringManager"
    )
    target.mkdir()
    with pytest.raises(docs.DocsError):
        docs.supersede_folder(folder, NOW)
    assert (folder / "AlanBron_Resume_AcmeLogistics_202609.docx").read_bytes() == (
        b"edited by hand"
    )
    assert list(target.iterdir()) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_read_only_parent_refuses_and_leaves_folder_untouched(folder):
    parent = folder.parent
    parent.chmod(0o555)
    try:
        with pytest.raises(docs.DocsError):
            docs.supersede_folder(folder, NOW)
    finally:
        parent.chmod(0o755)
    assert (folder / "AlanBron_Resume_AcmeLogistics_202609.docx").read_bytes() == (
        b"edited by hand"
    )


def test_a_folder_without_the_month_prefix_is_refused(tmp_path):
    odd = tmp_path / "NoUnderscoreHere"
    odd.mkdir()
    with pytest.raises(docs.DocsError):
        docs.supersede_folder(odd, NOW)
    assert odd.is_dir()
