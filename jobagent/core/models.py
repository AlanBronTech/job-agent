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

import re
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


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


_PERIOD_RE = re.compile(r"^(?:19|20)\d{2}(?:-(?:0[1-9]|1[0-2]))?$")

PRESENT = "present"


def _coerce_period(value: object) -> object:
    """Normalise a role date to ``YYYY`` or ``YYYY-MM``, both as strings.

    YAML hands us a bare year as an int and a quoted ``2017-07`` as a str.
    Both are legitimate resume precision — month granularity is what makes a
    tenure gap visible — so both are kept rather than forced to one.
    """
    if isinstance(value, int):
        value = str(value)
    if isinstance(value, str) and not _PERIOD_RE.match(value):
        raise ValueError(f"{value!r} is not a year (2021) or year-month (2021-06)")
    return value


def _coerce_period_end(value: object) -> object:
    """As ``_coerce_period``, plus the ``present`` sentinel for a current role."""
    if value == PRESENT:
        return value
    return _coerce_period(value)


PeriodStart = Annotated[str, BeforeValidator(_coerce_period)]
PeriodEnd = Annotated[str, BeforeValidator(_coerce_period_end)]


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
    # Work rights are a scoreable JD requirement in the AU market, so this is
    # data the scorer reads, not decoration.
    citizenship: str | None = None
    headline: str
    positioning: str
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)


class FounderEntry(_Base):
    id: str
    company: str
    role: str
    visibility: Visibility
    # Optional: a founder entry may be open-ended or deliberately undated.
    start: PeriodStart | None = None
    end: PeriodEnd | None = None
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
    start: PeriodStart
    end: PeriodEnd
    sector: str
    visibility: Visibility
    # Stack actually used in the role. Read directly by the fit scorer when a
    # JD names technologies, so it stays structured rather than prose.
    tech: list[str] = Field(default_factory=list)
    departure_reason: str | None = None
    # Guidance that applies to the role as a whole rather than one bullet —
    # e.g. a title that understates the scope, or a correction worth not
    # re-making. Bullet-level notes live on Bullet.
    note_for_scorer: str | None = None
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
    gap_2023: str | None = None
    gap_2025: str | None = None
    gap_answer_rules: list[str] = Field(default_factory=list)
    why_leaving_current: str | None = None
    outside_interests: str | None = None
    salary_expectation: str | None = None
    stack_mismatch: str | None = None
    quality_under_pressure: str | None = None


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
    # What the commute ceiling is measured against (e.g. "hybrid"). The limit
    # is meaningless to the scorer without it — see max_commute_rationale,
    # which records that no on-site-only figure has been confirmed.
    max_commute_basis: str | None = None
    max_commute_rationale: str
    min_salary_aud: int
    work_types: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class Narrative(_Base):
    """The through-line every application has to tell the same way.

    Separate from ``Differentiator``, which is material to deploy. This is the
    constraint on how material may be deployed: same facts, same reasons,
    shifting emphasis only.
    """

    spine: str | None = None
    threads: list[str] = Field(default_factory=list)
    consistency_rules: list[str] = Field(default_factory=list)


class AssetsFile(_Base):
    narrative: Narrative = Field(default_factory=Narrative)
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


# --------------------------------------------------------------------------- #
# Job descriptions (Phase 2)
# --------------------------------------------------------------------------- #


class WorkType(str, Enum):
    """Employment basis. ``unknown`` is a first-class value, not a failure.

    Kept aligned with ``assets.yaml`` target_filters.work_types so a JD can be
    matched against Alan's stated preferences without a translation layer. A JD
    that doesn't say gets ``unknown`` rather than a guess.
    """

    permanent = "permanent"
    contract = "contract"
    fixed_term = "fixed_term"
    unknown = "unknown"


class WorkArrangement(str, Enum):
    """Where the work happens.

    Not in the BUILD_PLAN field list, but Alan's hardest filter is a commute
    ceiling that applies differently to hybrid and on-site roles
    (``target_filters.max_commute_basis``). Without this the scorer cannot
    apply that constraint at all.
    """

    onsite = "onsite"
    hybrid = "hybrid"
    remote = "remote"
    unknown = "unknown"


class SalaryRange(_Base):
    """Advertised salary. ``raw`` preserves the JD's own wording.

    Split into numbers because ``min_salary_aud`` filtering needs them, and
    kept alongside the original text because ranges are advertised in wildly
    inconsistent forms (packages, inc. super, day rates, "competitive").
    """

    min_aud: int | None = None
    max_aud: int | None = None
    includes_super: bool | None = None
    raw: str | None = None


class JobDescription(_Base):
    """A parsed job ad.

    ``id`` is assigned by the store on insert; an unsaved JD has none.
    ``raw_text`` is never discarded — every downstream claim must be checkable
    against the source, and re-parsing after a prompt change needs the original.
    """

    id: int | None = None

    title: str
    company: str | None = None
    location: str | None = None
    work_type: WorkType = WorkType.unknown
    work_arrangement: WorkArrangement = WorkArrangement.unknown
    salary_range: SalaryRange | None = None
    seniority: str | None = None

    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)

    source: str | None = None
    raw_text: str
    ingested_at: datetime
