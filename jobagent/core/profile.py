"""Load and validate the profile from a directory of YAML files + voice.md.

Pure logic: no printing, no sys.exit, no typer. On any problem it raises
``ProfileError`` carrying a human-readable, multi-line message. The CLI renders
that message and sets the exit code; a web handler would return it as a 400.

Validation happens in three stages, each attributing failure to its file:

1. YAML parse — reported as ``filename:line:col: problem`` (never a traceback).
2. Schema — pydantic, with unknown keys and bad enum values rejected.
3. Cross-reference — ``linked_story`` must resolve to a real story id,
   ``question_types`` must come from the controlled vocabulary, and ids must be
   unique within their collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from jobagent.core.models import (
    AssetsFile,
    Profile,
    RolesFile,
    StoriesFile,
    Visibility,
)

ROLES_FILE = "roles.yaml"
STORIES_FILE = "stories.yaml"
ASSETS_FILE = "assets.yaml"
VOICE_FILE = "voice.md"


class ProfileError(Exception):
    """Any failure loading or validating the profile. The message is intended
    to be shown to a human as-is."""


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_profile(profile_dir: str | Path) -> Profile:
    """Load, validate and cross-reference the profile in ``profile_dir``.

    Raises ``ProfileError`` on the first stage that fails.
    """
    profile_dir = Path(profile_dir)
    if not profile_dir.is_dir():
        raise ProfileError(f"Profile directory not found: {profile_dir}")

    roles = _parse_model(
        RolesFile, _load_yaml(profile_dir / ROLES_FILE), ROLES_FILE
    )
    stories = _parse_model(
        StoriesFile, _load_yaml(profile_dir / STORIES_FILE), STORIES_FILE
    )
    assets = _parse_model(
        AssetsFile, _load_yaml(profile_dir / ASSETS_FILE), ASSETS_FILE
    )
    voice = _read_text(profile_dir / VOICE_FILE)

    profile = Profile(roles=roles, stories=stories, assets=assets, voice=voice)
    _validate_cross_references(profile)
    return profile


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ProfileError(f"Profile file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProfileError(_format_yaml_error(path, exc)) from exc
    if data is None:
        raise ProfileError(f"{path.name}: file is empty")
    if not isinstance(data, dict):
        raise ProfileError(
            f"{path.name}: expected a top-level mapping, got "
            f"{type(data).__name__}"
        )
    return data


def _read_text(path: Path) -> str:
    if not path.exists():
        raise ProfileError(f"Profile file not found: {path}")
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Error formatting
# --------------------------------------------------------------------------- #


def _format_yaml_error(path: Path, exc: yaml.YAMLError) -> str:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or "invalid YAML"
    if mark is not None:
        # PyYAML marks are 0-indexed; humans count from 1.
        return f"{path.name}:{mark.line + 1}:{mark.column + 1}: {problem}"
    return f"{path.name}: {problem}"


def _parse_model(model: type[BaseModel], data: dict, filename: str):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ProfileError(_format_validation_error(filename, exc)) from exc


def _format_validation_error(filename: str, exc: ValidationError) -> str:
    lines = [
        f"{filename}: schema validation failed "
        f"({exc.error_count()} error(s)):"
    ]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        msg = err["msg"]
        # For enum failures, name what was actually supplied.
        if err["type"].startswith("enum") and "input" in err:
            msg = f"{msg} (got {err['input']!r})"
        lines.append(f"  - {loc}: {msg}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Cross-reference validation
# --------------------------------------------------------------------------- #


def _validate_cross_references(profile: Profile) -> None:
    errors: list[str] = []

    story_ids = [s.id for s in profile.stories.stories]
    errors.extend(_duplicate_ids("stories", story_ids))

    known_stories = set(story_ids)
    vocabulary = set(profile.stories.question_type_vocabulary)

    # linked_story on any bullet must resolve to a real story id.
    bullet_sections = (
        ("founder_track_record", profile.roles.founder_track_record),
        ("ai_capability", profile.roles.ai_capability),
        ("roles", profile.roles.roles),
    )
    for section_name, entries in bullet_sections:
        errors.extend(_duplicate_ids(section_name, [e.id for e in entries]))
        for entry in entries:
            for i, bullet in enumerate(entry.bullets):
                if bullet.linked_story and bullet.linked_story not in known_stories:
                    errors.append(
                        f"{section_name}[{entry.id}].bullets[{i}].linked_story "
                        f"references unknown story '{bullet.linked_story}'"
                    )

    # question_types must come from the controlled vocabulary.
    for story in profile.stories.stories:
        for qt in story.question_types:
            if qt not in vocabulary:
                errors.append(
                    f"stories[{story.id}].question_types: '{qt}' is not in "
                    "question_type_vocabulary"
                )

    if errors:
        raise ProfileError(
            "Cross-reference validation failed:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def _duplicate_ids(section_name: str, ids: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for id_ in ids:
        if id_ in seen and id_ not in dupes:
            dupes.append(id_)
        seen.add(id_)
    return [f"{section_name}: duplicate id '{d}'" for d in dupes]


# --------------------------------------------------------------------------- #
# Summary (pure computation; the CLI renders it)
# --------------------------------------------------------------------------- #


@dataclass
class ProfileSummary:
    section_counts: dict[str, int] = field(default_factory=dict)
    visibility_breakdown: dict[str, int] = field(default_factory=dict)
    evidence_breakdown: dict[str, int] = field(default_factory=dict)


def summarize_profile(profile: Profile) -> ProfileSummary:
    roles = profile.roles
    stories = profile.stories
    assets = profile.assets

    section_counts = {
        "founder_track_record": len(roles.founder_track_record),
        "ai_capability": len(roles.ai_capability),
        "roles": len(roles.roles),
        "earlier_career": len(roles.earlier_career),
        "skill_categories": len(roles.skills),
        "excluded_skills": len(roles.excluded_skills),
        "stories": len(stories.stories),
        "differentiators": len(assets.differentiators),
        "target_roles": len(assets.target_roles),
    }

    visibility = {v.value: 0 for v in Visibility}
    for entry in (
        *roles.founder_track_record,
        *roles.ai_capability,
        *roles.roles,
        *roles.earlier_career,
    ):
        visibility[entry.visibility.value] += 1

    evidence = {"strong": 0, "moderate": 0, "weak": 0}
    for entry in (
        *roles.founder_track_record,
        *roles.ai_capability,
        *roles.roles,
    ):
        for bullet in entry.bullets:
            evidence[bullet.evidence_strength.value] += 1
    for early in roles.earlier_career:
        evidence[early.evidence_strength.value] += 1

    return ProfileSummary(
        section_counts=section_counts,
        visibility_breakdown=visibility,
        evidence_breakdown=evidence,
    )