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
