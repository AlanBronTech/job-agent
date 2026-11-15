"""services.masters: the master chosen for an ad, shown wherever the assessment is.

Free and read-only: choosing a master never builds a model client.
"""

from __future__ import annotations

from datetime import datetime, timezone

from jobagent.core.masters import describe_choice
from jobagent.core.models import (
    JobDescription,
    MasterChoice,
    RoleClassification,
    RoleKind,
    WorkType,
)
from jobagent.services import masters
from jobagent.services.workspace import Workspace
from tests.ui_seed import masters_profile, workspace


def ad(title: str, work_type: WorkType = WorkType.permanent) -> JobDescription:
    return JobDescription(title=title, work_type=work_type, raw_text=title,
                          ingested_at=datetime(2026, 11, 16, tzinfo=timezone.utc))


def ws_with(tmp_path, profile_dir) -> Workspace:
    return Workspace(**{**workspace(tmp_path).__dict__, "profile_dir": profile_dir})


def test_chooses_from_the_registry(tmp_path):
    ws = ws_with(tmp_path, masters_profile(tmp_path))
    kind = RoleClassification(primary=RoleKind.ai_enablement, reason="Invented.")
    choice = masters.choose(ws, ad("AI Enablement Lead"), kind)
    assert choice.master.id == "ai"


def test_no_registry_or_no_profile_means_no_choice(tmp_path):
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "profile.example"
    assert masters.choose(ws_with(tmp_path, example), ad("Engineering Manager"), None) is None
    assert masters.choose(ws_with(tmp_path, None), ad("Engineering Manager"), None) is None


def test_a_broken_registry_is_reported_not_raised(tmp_path):
    profile = masters_profile(tmp_path)
    (profile / "resumes" / "Sam-Resume-AI.docx").unlink()
    choice = masters.choose(ws_with(tmp_path, profile), ad("Engineering Manager"), None)
    assert choice.master is None and not choice.not_a_target
    assert "masters.yaml" in choice.reason and "Sam-Resume-AI.docx" in choice.reason


def test_describe_a_master_names_the_file_to_send(tmp_path):
    ws = ws_with(tmp_path, masters_profile(tmp_path))
    choice = masters.choose(ws, ad("Engineering Manager"), None)
    text = describe_choice(choice)
    assert text.startswith("Engineering Manager: a manager role.")
    assert "Sam-Resume-Manager.pdf" in text  # the PDF when there is one


def test_describe_falls_back_to_the_docx(tmp_path):
    ws = ws_with(tmp_path, masters_profile(tmp_path))
    choice = masters.choose(ws, ad("Senior Software Engineer", WorkType.contract), None)
    assert "Sam-Resume-Contract.docx" in describe_choice(choice)


def test_describe_not_a_target():
    choice = MasterChoice(not_a_target=True, reason="A permanent hands-on engineering role.")
    assert describe_choice(choice) == "Not a target. A permanent hands-on engineering role."
