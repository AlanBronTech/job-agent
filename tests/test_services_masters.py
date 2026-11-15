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


# -- which resume went: resolved when an application is recorded --------------

import pytest  # noqa: E402

from jobagent.core import store  # noqa: E402
from jobagent.services.refusals import UnknownMaster  # noqa: E402


def stored_ad(ws, title: str, work_type: WorkType = WorkType.permanent) -> int:
    with store.open_store(ws.db_path) as conn:
        return store.add_jd(conn, ad(title, work_type))


@pytest.fixture
def mws(tmp_path):
    return ws_with(tmp_path, masters_profile(tmp_path))


def test_nothing_named_assumes_the_suggested_master_and_its_pdf(mws):
    jd_id = stored_ad(mws, "Engineering Manager")
    r = masters.resolve_sent(mws, jd_id)
    assert (r.master, r.suggested, r.assumed) == ("manager", "manager", True)
    assert r.file.name == "Sam-Resume-Manager.pdf"


def test_a_named_master_is_recorded_as_an_override(mws):
    jd_id = stored_ad(mws, "Engineering Manager")
    r = masters.resolve_sent(mws, jd_id, chosen="ai")
    assert (r.master, r.suggested, r.assumed) == ("ai", "manager", False)
    assert r.overrode and r.file.name == "Sam-Resume-AI.docx"  # no PDF: the .docx


def test_custom_records_custom_and_no_file(mws):
    jd_id = stored_ad(mws, "Engineering Manager")
    r = masters.resolve_sent(mws, jd_id, chosen="custom")
    assert r.master == "custom" and r.file is None


def test_a_sent_file_identical_to_a_master_is_that_master(mws, tmp_path):
    jd_id = stored_ad(mws, "Engineering Manager")
    copy = tmp_path / "renamed.pdf"
    copy.write_bytes((mws.profile_dir / "resumes" / "Sam-Resume-Manager.pdf").read_bytes())
    r = masters.resolve_sent(mws, jd_id, sent_resume=copy)
    assert r.master == "manager" and r.file is None and not r.assumed


def test_any_other_sent_file_is_custom(mws, tmp_path):
    jd_id = stored_ad(mws, "Engineering Manager")
    other = tmp_path / "AlanBron_Resume_Acme.docx"
    other.write_bytes(b"a generated resume")
    assert masters.resolve_sent(mws, jd_id, sent_resume=other).master == "custom"


def test_sent_as_generated_is_custom(mws):
    jd_id = stored_ad(mws, "Engineering Manager")
    assert masters.resolve_sent(mws, jd_id, sent_as_generated=True).master == "custom"


def test_not_a_target_records_nothing_unless_named(mws):
    jd_id = stored_ad(mws, "Senior Software Engineer")
    r = masters.resolve_sent(mws, jd_id)
    assert r.master is None and r.suggested == "not_a_target" and r.file is None
    assert masters.resolve_sent(mws, jd_id, chosen="contract").master == "contract"


def test_an_unknown_master_is_refused(mws):
    jd_id = stored_ad(mws, "Engineering Manager")
    with pytest.raises(UnknownMaster) as refused:
        masters.resolve_sent(mws, jd_id, chosen="executive")
    assert refused.value.known == ["manager", "ai", "contract"]


def test_without_a_registry_nothing_is_recorded(tmp_path):
    ws = ws_with(tmp_path, None)
    jd_id = stored_ad(ws, "Engineering Manager")
    r = masters.resolve_sent(ws, jd_id)
    assert r.master is None and r.suggested is None
    assert masters.resolve_sent(ws, jd_id, chosen="custom").master == "custom"
    with pytest.raises(UnknownMaster):
        masters.resolve_sent(ws, jd_id, chosen="manager")


def test_nothing_named_again_does_not_record_a_second_copy(mws):
    from datetime import datetime, timezone

    from jobagent.core.models import Application, ApplicationStatus

    jd_id = stored_ad(mws, "Engineering Manager")
    with store.open_store(mws.db_path) as conn:
        store.save_application(conn, Application(
            jd_id=jd_id, status=ApplicationStatus.applied, resume_master="ai",
            updated_at=datetime.now(timezone.utc)))
    r = masters.resolve_sent(mws, jd_id)
    assert r.master is None and r.file is None  # leaves "ai" as it is
