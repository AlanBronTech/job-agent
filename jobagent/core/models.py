"""Pydantic models shared across the agent.

Phase 1 defines the profile schema. As later phases land, JobDescription,
FitAssessment and friends join this module.

Two policies are enforced structurally rather than by prose:

* ``extra="forbid"`` on every model. A misspelled key (``linked_stroy``) is a
  silent data-loss bug in a data-driven profile — the bullet quietly loses its
  story link and the dangling-reference check never fires. Forbidding unknown
  keys turns that into a loud validation error, and keeps ``profile.example``
  honest as the documented schema.
* ``visibility`` and ``evidence_strength`` are enums, so an invalid value is
  rejected at load time with the allowed set named in the error.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Visibility(str, Enum):
    """Controls how a profile entry is rendered.

    full        -> title, company, dates, bullets
    summary     -> one condensed line, no dates
    scorer_only -> never rendered; context for fit scoring only
    """

    full = "full"
    summary = "summary"
    scorer_only = "scorer_only"


class EvidenceStrength(str, Enum):
    """How well a claim survives a drill-down.

    strong   = numbers attached; survives a 20-minute interrogation.
    moderate = true and defensible, but thin on specifics.
    weak     = uncomfortable to be challenged on; a partial match at best.
    """

    strong = "strong"
    moderate = "moderate"
    weak = "weak"


class _Base(BaseModel):
    """Shared config: reject unknown keys everywhere."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# roles.yaml
# --------------------------------------------------------------------------- #


class Bullet(_Base):
    text: str
    tags: list[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrength
    note_for_scorer: str | None = None
    linked_story: str | None = None


class Education(_Base):
    qualification: str
    institution: str
    # No year, by age-signal policy. Modelled optional in case a qualification
    # legitimately needs one; the loader does not require it.
    year: int | None = None


class Certification(_Base):
    name: str
    issuer: str


class Person(_Base):
    name: str
    location: str
    email: str
    phone: str
    linkedin: str | None = None
    github: str | None = None
    headline: str
    positioning: str
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)


class FounderEntry(_Base):
    id: str
    company: str
    role: str
    visibility: Visibility
    bullets: list[Bullet]
    note_for_scorer: str | None = None


class AiCapabilityEntry(_Base):
    id: str
    label: str
    visibility: Visibility
    bullets: list[Bullet]
    note_for_scorer: str | None = None
    caveats: list[str] = Field(default_factory=list)


class Role(_Base):
    id: str
    title: str
    company: str
    location: str
    start: int
    end: int
    sector: str
    visibility: Visibility
    departure_reason: str | None = None
    anchor_story: bool = False
    bullets: list[Bullet]


class EarlierRole(_Base):
    id: str
    company: str
    role: str
    visibility: Visibility
    summary: str
    tags: list[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrength


class ExcludedSkill(_Base):
    skill: str
    reason: str


class RolesFile(_Base):
    person: Person
    available_tags: list[str] = Field(default_factory=list)
    founder_track_record: list[FounderEntry] = Field(default_factory=list)
    ai_capability: list[AiCapabilityEntry] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=list)
    earlier_career: list[EarlierRole] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    excluded_skills: list[ExcludedSkill] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# stories.yaml
# --------------------------------------------------------------------------- #


class Story(_Base):
    id: str
    label: str
    question_types: list[str] = Field(default_factory=list)
    strength: EvidenceStrength
    situation: str
    task: str
    action: str
    result: str
    what_id_do_differently: str | None = None
    note_for_scorer: str | None = None


class Explanations(_Base):
    employment_gap: str | None = None
    gap_answer_rules: list[str] = Field(default_factory=list)
    why_leaving_current: str | None = None
    salary_expectation: str | None = None
    stack_mismatch: str | None = None


class StoriesFile(_Base):
    question_type_vocabulary: list[str] = Field(default_factory=list)
    stories: list[Story] = Field(default_factory=list)
    explanations: Explanations = Field(default_factory=Explanations)


# --------------------------------------------------------------------------- #
# assets.yaml
# --------------------------------------------------------------------------- #


class Differentiator(_Base):
    id: str
    label: str
    detail: str
    use_when: list[str] = Field(default_factory=list)
    strength: EvidenceStrength
    note_for_scorer: str | None = None


class TargetFilters(_Base):
    location: str
    max_commute_minutes: int
    max_commute_rationale: str
    min_salary_aud: int
    work_types: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class AssetsFile(_Base):
    differentiators: list[Differentiator] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    target_filters: TargetFilters
    positive_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Aggregate
# --------------------------------------------------------------------------- #


class Profile(_Base):
    """The whole profile: the three YAML files plus voice.md, validated and
    cross-referenced."""

    roles: RolesFile
    stories: StoriesFile
    assets: AssetsFile
    voice: str
