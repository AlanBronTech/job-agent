"""The master-resume registry: `<profile>/resumes/masters.yaml`.

The masters are hand-written documents. JobAgent only needs to know where each
one is and what it is for; it never writes or edits them. Every test builds
its own registry in a temporary profile folder with invented names.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobagent.core.masters import MASTERS_FILE, RESUMES_DIR, load_masters
from jobagent.core.models import RoleKind, WorkType
from jobagent.core.profile import ProfileError

VALID = """\
masters:
  - id: manager
    label: Engineering Manager
    docx: Sam-Resume-Manager.docx
    pdf: Sam-Resume-Manager.pdf
    default: true
    use_for: >-
      Engineering Manager and Software Development Manager roles.
  - id: ai
    label: AI adoption lead
    docx: Sam-Resume-AI.docx
    pdf: Sam-Resume-AI.pdf
    role_kinds: [ai_enablement]
    use_for: AI enablement and adoption roles.
    not_for: Roles that require shipped production LLM systems.
  - id: contract
    label: Contract engineer
    docx: Sam-Resume-Contract.docx
    pdf: Sam-Resume-Contract.pdf
    work_types: [contract, fixed_term]
    use_for: Contract roles only.
"""

FILES = [
    "Sam-Resume-Manager.docx", "Sam-Resume-Manager.pdf",
    "Sam-Resume-AI.docx", "Sam-Resume-AI.pdf",
    "Sam-Resume-Contract.docx", "Sam-Resume-Contract.pdf",
]


def _registry(tmp_path: Path, text: str = VALID, files: list[str] = FILES) -> Path:
    folder = tmp_path / RESUMES_DIR
    folder.mkdir()
    (folder / MASTERS_FILE).write_text(text, encoding="utf-8")
    for name in files:
        (folder / name).write_bytes(b"x")
    return tmp_path


def test_loads_every_master_with_absolute_paths(tmp_path: Path) -> None:
    masters = load_masters(_registry(tmp_path))

    assert [m.id for m in masters] == ["manager", "ai", "contract"]
    manager = masters[0]
    assert manager.default is True
    assert manager.docx == tmp_path / RESUMES_DIR / "Sam-Resume-Manager.docx"
    assert manager.pdf == tmp_path / RESUMES_DIR / "Sam-Resume-Manager.pdf"
    assert masters[1].role_kinds == [RoleKind.ai_enablement]
    assert masters[1].not_for == "Roles that require shipped production LLM systems."
    assert masters[2].work_types == [WorkType.contract, WorkType.fixed_term]


def test_no_registry_means_no_masters(tmp_path: Path) -> None:
    # Masters are optional: without them, generate works exactly as before.
    assert load_masters(tmp_path) == []


def test_pdf_is_optional(tmp_path: Path) -> None:
    text = VALID.replace("    pdf: Sam-Resume-AI.pdf\n", "")
    files = [f for f in FILES if f != "Sam-Resume-AI.pdf"]
    masters = load_masters(_registry(tmp_path, text, files))
    assert masters[1].pdf is None


def test_a_missing_document_is_named(tmp_path: Path) -> None:
    files = [f for f in FILES if f != "Sam-Resume-Contract.docx"]
    with pytest.raises(ProfileError, match="Sam-Resume-Contract.docx"):
        load_masters(_registry(tmp_path, files=files))


def test_docx_must_be_a_word_file(tmp_path: Path) -> None:
    text = VALID.replace("docx: Sam-Resume-AI.docx", "docx: Sam-Resume-AI.pdf")
    with pytest.raises(ProfileError, match="docx"):
        load_masters(_registry(tmp_path, text))


def test_exactly_one_default(tmp_path: Path) -> None:
    none = VALID.replace("    default: true\n", "")
    with pytest.raises(ProfileError, match="default"):
        load_masters(_registry(tmp_path, none))


def test_two_defaults_is_an_error(tmp_path: Path, tmp_path_factory) -> None:
    two = VALID.replace(
        "    role_kinds: [ai_enablement]\n",
        "    role_kinds: [ai_enablement]\n    default: true\n",
    )
    with pytest.raises(ProfileError, match="default"):
        load_masters(_registry(tmp_path, two))


def test_ids_are_unique(tmp_path: Path) -> None:
    text = VALID.replace("id: contract", "id: ai")
    with pytest.raises(ProfileError, match="ai"):
        load_masters(_registry(tmp_path, text))


def test_unknown_role_kind_is_rejected(tmp_path: Path) -> None:
    text = VALID.replace("[ai_enablement]", "[ai_wizardry]")
    with pytest.raises(ProfileError, match="ai_wizardry"):
        load_masters(_registry(tmp_path, text))


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    text = VALID.replace("    use_for: Contract roles only.\n",
                         "    use_for: Contract roles only.\n    colour: blue\n")
    with pytest.raises(ProfileError, match="colour"):
        load_masters(_registry(tmp_path, text))


def test_yaml_error_names_the_line(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match=r"masters\.yaml:\d+:\d+"):
        load_masters(_registry(tmp_path, "masters:\n  - id: [unclosed\n"))


def test_an_empty_list_is_an_error(tmp_path: Path) -> None:
    # A registry that exists but lists nothing is a mistake, not "no masters".
    with pytest.raises(ProfileError, match="no masters"):
        load_masters(_registry(tmp_path, "masters: []\n", []))


# --------------------------------------------------------------------------- #
# `jobagent profile validate` reports the masters too
# --------------------------------------------------------------------------- #


def _profile_with_masters(tmp_path: Path, example_dir: Path, text: str = VALID,
                          files: list[str] = FILES) -> Path:
    import shutil

    profile = tmp_path / "profile"
    shutil.copytree(example_dir, profile)
    _registry(profile, text, files)
    return profile


def test_validate_lists_the_masters(tmp_path: Path, example_dir: Path) -> None:
    from typer.testing import CliRunner

    from jobagent.cli.main import app

    profile = _profile_with_masters(tmp_path, example_dir)
    result = CliRunner().invoke(app, ["profile", "validate", "--dir", str(profile)])

    assert result.exit_code == 0, result.output
    assert "Engineering Manager" in result.output
    assert "default" in result.output
    assert "Contract engineer" in result.output


def test_validate_fails_on_a_bad_registry(tmp_path: Path, example_dir: Path) -> None:
    from typer.testing import CliRunner

    from jobagent.cli.main import app

    files = [f for f in FILES if f != "Sam-Resume-AI.docx"]
    profile = _profile_with_masters(tmp_path, example_dir, files=files)
    result = CliRunner().invoke(app, ["profile", "validate", "--dir", str(profile)])

    assert result.exit_code == 1
    assert "Sam-Resume-AI.docx" in result.output


# --------------------------------------------------------------------------- #
# Choosing a master for an ad
# --------------------------------------------------------------------------- #

from datetime import datetime, timezone  # noqa: E402

from jobagent.core.masters import select_master  # noqa: E402
from jobagent.core.models import (  # noqa: E402
    JobDescription,
    MasterResume,
    RoleClassification,
)

MASTERS = [
    MasterResume(id="em", label="Engineering Manager", docx=Path("/r/em.docx"),
                 default=True, use_for="Manager roles."),
    MasterResume(id="ai", label="AI adoption lead", docx=Path("/r/ai.docx"),
                 role_kinds=[RoleKind.ai_enablement], use_for="AI adoption roles."),
    MasterResume(id="contract", label="Contract senior engineer",
                 docx=Path("/r/contract.docx"),
                 work_types=[WorkType.contract, WorkType.fixed_term],
                 use_for="Contracts only."),
]


def jd(title: str, work_type: WorkType = WorkType.permanent) -> JobDescription:
    return JobDescription(title=title, work_type=work_type, raw_text=title,
                          ingested_at=datetime(2026, 11, 16, tzinfo=timezone.utc))


def kind(primary: str, secondary: str | None = None) -> RoleClassification:
    return RoleClassification(primary=primary, secondary=secondary, reason="test")


def pick(title, work_type=WorkType.permanent, classification=None, masters=MASTERS):
    return select_master(jd(title, work_type), classification, masters)


@pytest.mark.parametrize(
    "title, work_type, classification, expected",
    [
        # Contracts take the contract master, whatever else the ad says.
        ("Senior Software Engineer", WorkType.contract, kind("technical_lead"), "contract"),
        ("Senior Software Engineering Position", WorkType.fixed_term, kind("technical_lead"), "contract"),
        ("Senior Software AI Engineer", WorkType.contract, kind("ai_enablement", "technical_lead"), "contract"),
        # AI adoption leadership.
        ("AI Enablement Lead - Software Engineering", WorkType.permanent, kind("ai_enablement", "technical_lead"), "ai"),
        ("AI Product Lead", WorkType.permanent, kind("ai_enablement", "delivery_focused"), "ai"),
        ("Senior Manager, AI Product Delivery Engineering", WorkType.permanent, kind("ai_enablement"), "ai"),
        # Manager roles, including AI-flavoured ones that lead with people.
        ("Engineering Manager", WorkType.permanent, kind("people_focused"), "em"),
        ("AI Engineering Manager", WorkType.permanent, kind("people_focused", "ai_enablement"), "em"),
        ("Head of Engineering - AI Platform", WorkType.permanent, kind("technical_lead", "ai_enablement"), "em"),
        ("Engineering Manager / Squad Tech Lead", WorkType.permanent, kind("technical_lead", "people_focused"), "em"),
        ("Engineering Manager - Technology", WorkType.permanent, kind("technical_lead", "people_focused"), "em"),
        ("Software Engineer Manager, Payments Platform", WorkType.permanent, None, "em"),
        # A contract that is a management job is still a management job.
        ("Engineering Manager", WorkType.contract, kind("people_focused"), "em"),
        # Permanent Team Lead: the default until Alan decides (TBD).
        ("Engineering Team Lead", WorkType.permanent, kind("delivery_focused", "people_focused"), "em"),
        ("Digital Tech Lead", WorkType.permanent, kind("technical_lead"), "em"),
        # Delivery and project roles have no master of their own.
        ("Technology Project Manager", WorkType.permanent, kind("delivery_focused"), "em"),
        # Not classified yet: the title and work type still decide.
        ("Engineering Manager", WorkType.unknown, None, "em"),
    ],
)
def test_picks_the_master(title, work_type, classification, expected) -> None:
    choice = pick(title, work_type, classification)
    assert choice is not None
    assert choice.not_a_target is False
    assert choice.master is not None and choice.master.id == expected
    assert choice.reason


@pytest.mark.parametrize(
    "title, work_type, classification",
    [
        ("Senior Software Engineer", WorkType.permanent, kind("technical_lead")),
        ("Applied AI Engineer", WorkType.permanent, kind("ai_enablement")),
        ("Senior Full Stack Developer", WorkType.permanent, None),
        ("Agentic AI Architect", WorkType.permanent, kind("technical_lead")),
    ],
)
def test_permanent_hands_on_roles_are_not_a_target(title, work_type, classification) -> None:
    choice = pick(title, work_type, classification)
    assert choice.not_a_target is True
    assert choice.master is None
    assert "permanent" in choice.reason


def test_hands_on_role_with_unstated_terms_asks_about_them() -> None:
    choice = pick("AI Engineer", WorkType.unknown, kind("ai_enablement"))
    assert choice.not_a_target is True
    assert "contract" in choice.reason


def test_the_reason_names_contract_for_a_contract_manager_role() -> None:
    choice = pick("Engineering Manager", WorkType.contract, kind("people_focused"))
    assert "contract" in choice.reason.lower()


def test_team_lead_reason_says_it_is_undecided() -> None:
    choice = pick("Engineering Team Lead", WorkType.permanent, kind("people_focused"))
    assert "Team Lead" in choice.reason


def test_no_masters_means_no_choice() -> None:
    assert pick("Engineering Manager", masters=[]) is None


def test_contract_without_a_contract_master_is_not_a_target() -> None:
    masters = [m for m in MASTERS if m.id != "contract"]
    choice = pick("Senior Software Engineer", WorkType.contract, None, masters)
    assert choice.not_a_target is True


def test_ai_role_without_an_ai_master_falls_back_to_the_default() -> None:
    masters = [m for m in MASTERS if m.id != "ai"]
    choice = pick("AI Enablement Lead", WorkType.permanent, kind("ai_enablement"), masters)
    assert choice.master.id == "em"


def test_ai_adoption_title_finds_the_ai_master_before_classification() -> None:
    # An ad scored before role kinds existed has no classification.
    choice = pick("AI & Digital Tools Adoption Lead", WorkType.fixed_term, None)
    assert choice.master.id == "ai"


def test_enablement_without_ai_is_not_the_ai_master() -> None:
    choice = pick("Engineering Enablement Manager", WorkType.permanent, None)
    assert choice.master.id == "em"


@pytest.mark.parametrize("title", [
    "Lead AI Engineer, Agentic Systems",
    "Agentic AI Architect (Lead / Principal)",
    "Lead Software Engineer",
])
def test_lead_engineer_titles_are_hands_on(title) -> None:
    # "Lead Engineer" is a senior hands-on title, not a team lead.
    choice = pick(title, WorkType.permanent, kind("technical_lead"))
    assert choice.not_a_target is True


def test_contract_delivery_lead_is_a_delivery_role() -> None:
    choice = pick("Delivery Lead - Data / Digital Platforms", WorkType.contract, None)
    assert choice.master.id == "em"
    assert "delivery" in choice.reason


def test_contract_project_manager_reason_is_delivery() -> None:
    choice = pick("Software Project Manager", WorkType.fixed_term, kind("delivery_focused"))
    assert "delivery" in choice.reason


def test_team_lead_classified_delivery_still_reads_as_team_lead() -> None:
    choice = pick("Engineering Team Lead", WorkType.permanent,
                  kind("delivery_focused", "people_focused"))
    assert "Team Lead" in choice.reason


def test_team_lead_pitched_at_manager_level_still_reads_as_team_lead() -> None:
    from jobagent.core.models import Seniority

    ad = jd("Engineering Team Lead").model_copy(update={"seniority": Seniority.manager})
    choice = select_master(ad, kind("delivery_focused", "people_focused"), MASTERS)
    assert choice.master.id == "em"
    assert "Team Lead" in choice.reason


# -- skills_order (spec 004, T020) ----------------------------------------------


def test_a_master_carries_its_skills_order(tmp_path: Path) -> None:
    text = VALID.replace("    default: true\n",
                         "    default: true\n    skills_order: [leadership, delivery]\n", 1)
    manager = load_masters(_registry(tmp_path, text))[0]
    assert manager.skills_order == ["leadership", "delivery"]


def test_a_skills_order_naming_a_category_the_profile_lacks_is_refused(tmp_path: Path) -> None:
    text = VALID.replace("    default: true\n",
                         "    default: true\n    skills_order: [leadership, juggling]\n", 1)
    folder = _registry(tmp_path, text)
    with pytest.raises(ProfileError, match="juggling"):
        load_masters(folder, skill_keys={"leadership", "delivery"})
    # Without the profile's keys the order is not checked.
    assert load_masters(folder)[0].skills_order == ["leadership", "juggling"]


def test_validate_checks_skills_order_against_the_profile(tmp_path: Path, example_dir: Path) -> None:
    from typer.testing import CliRunner

    from jobagent.cli.main import app

    text = VALID.replace("    default: true\n",
                         "    default: true\n    skills_order: [leadership, juggling]\n", 1)
    profile = _profile_with_masters(tmp_path, example_dir, text)
    result = CliRunner().invoke(app, ["profile", "validate", "--dir", str(profile)])
    assert result.exit_code == 1 and "juggling" in result.output
