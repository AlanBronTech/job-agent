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
from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


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
    # is meaningless to the scorer without it.
    max_commute_basis: str | None = None
    max_commute_rationale: str
    # Fully on-site roles are filtered by location, not by commute minutes —
    # five days a week is a different constraint from two, so the ceiling above
    # does not apply. An empty list means no on-site role passes.
    onsite_locations: list[str] = Field(default_factory=list)
    onsite_rationale: str | None = None
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


class Seniority(str, Enum):
    """The level the ad is pitched at, on one scale.

    Was free text, which across eleven real ads returned "Lead", "Manager",
    "Senior", "Engineering Manager" and ``null`` — five spellings of three
    ideas, comparable to nothing. The vocabulary is deliberately coarse: the
    scorer only needs to know whether a role sits below, at, or above Alan's
    target band, and any finer distinction is the ad's marketing rather than
    its substance. The advertised wording survives in ``title``.
    """

    junior = "junior"
    mid = "mid"
    senior = "senior"
    lead = "lead"          # tech lead, staff, principal — senior IC track
    manager = "manager"    # engineering manager, delivery manager
    director = "director"  # head of, director, GM, VP and above
    unknown = "unknown"


class HiringStatus(str, Enum):
    """Whether the ad is still taking applications.

    Both platforms say so plainly — "No longer accepting applications" on
    LinkedIn, an expired-job URL on Seek — and it was being discarded. For a
    live triage decision it is the most decisive fact on the page, and for the
    eval set it separates "they ghosted him" from "the ad had closed".
    """

    open = "open"
    closed = "closed"
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


# Under this many characters, an ad is far more likely to be a collapsed
# capture than a short advertisement. Measured over the fifteen ads in the drop
# folder: the collapsed Mattox capture yields 565 characters, the shortest
# whole ad (Care GP) 1,340. The gap is wide enough that this need not be
# clever. Lives here because both a fresh capture and a stored JD are judged
# by it, and they must be judged the same way.
THIN_AD_CHARS = 800


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
    seniority: Seniority = Seniority.unknown

    # Who put the ad up, and whether they are the employer. An agency blind ad
    # is a different proposition from a direct posting — there is nobody to
    # research, and the agency screens before the employer sees anything — and
    # ``company`` alone cannot express it, because for a blind ad company is
    # null precisely when this matters most.
    posted_by: str | None = None
    via_agency: bool = False

    hiring_status: HiringStatus = HiringStatus.unknown

    # One ad advertising several unnamed positions ("we're recruiting multiple
    # positions across our product engineering team"). Nothing about such an
    # ad can be tailored to, and it was being flattened into a single role with
    # no record that it had happened.
    multiple_roles: bool = False

    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)

    source: str | None = None
    # The ad's own URL, kept opaque. Never fetched — scraping Seek and
    # LinkedIn is a hard rule. It exists so a human can reopen the page.
    source_url: str | None = None
    # What the platform said about the posting itself, verbatim: how long it
    # has been live, how many have applied. Not part of the advertisement, but
    # an ad open five months with 100+ applicants is a signal the text never
    # carries. Left unparsed — two samples is not enough to know its shape.
    source_metadata: str | None = None
    raw_text: str
    ingested_at: datetime

    @property
    def thin(self) -> bool:
        """Too little ad text to draw conclusions from.

        The scorer reads two sentences with the same confidence it reads a
        ten-thousand-character ad: the Mattox stub (JD 23) produced five
        assessed "requirements" the ad never stated. Right verdict, wrong
        reasons. `score` refuses these without --force.
        """
        return len(self.raw_text) < THIN_AD_CHARS


# --------------------------------------------------------------------------- #
# Fit assessment (Phase 3)
# --------------------------------------------------------------------------- #


class MatchStatus(str, Enum):
    """How well the profile answers one requirement.

    ``partial`` is the honest home for transferable experience. A requirement
    answered by adjacent work is not met, and calling it met is how a scorer
    talks its owner into a day of wasted effort.
    """

    met = "met"
    partial = "partial"
    gap = "gap"


class Verdict(str, Enum):
    apply = "apply"
    apply_with_caveats = "apply_with_caveats"
    skip = "skip"


class ConstraintStatus(str, Enum):
    """Whether one of Alan's stated hard filters is satisfied.

    ``unknown`` is the important value and the reason these are checked in
    code rather than asked of a model. The CareGP ad said "on-site" and named
    no suburb; ``assets.yaml`` says such an ad must not be scored as a fit
    until the suburb is known. That is a third state, and a boolean cannot
    hold it.
    """

    ok = "ok"
    breach = "breach"
    unknown = "unknown"


class ConstraintCheck(_Base):
    """One hard filter from ``target_filters``, evaluated against one ad.

    Computed in Python, never by the model. These are arithmetic and set
    membership against values Alan has already decided — a model would apply
    them inconsistently, and inconsistency here means the tool argues him into
    a role he has already ruled out.
    """

    name: str
    status: ConstraintStatus
    detail: str
    # What to ask before applying, when the ad simply does not say.
    question: str | None = None


class RequirementMatch(_Base):
    requirement: str
    status: MatchStatus
    # Which profile entry evidences it: a role id, story id, differentiator id
    # or founder-entry id. Required for `met` — an uncitable claim is not met.
    evidence_ref: str | None = None
    note: str


class ChallengePoint(_Base):
    point: str
    response: str


class FitAssessment(_Base):
    """The output of scoring one ad against the profile.

    Two scores, because two different readers decide in sequence and they do
    not read the same way. ``recruiter_screen_score`` is what survives a
    keyword pass by someone who is not an engineer; ``overall_score`` is what
    a hiring manager reading properly would conclude. Most rejections in the
    recorded outcomes happened at the first, and a tool that reports only the
    second explains none of them.
    """

    id: int | None = None
    jd_id: int

    overall_score: int = Field(ge=0, le=100)
    recruiter_screen_score: int = Field(ge=0, le=100)

    @field_validator("overall_score", "recruiter_screen_score", mode="before")
    @classmethod
    def _round_a_float(cls, value: object) -> object:
        """A model that answers 62.0, or 62.5, means 62.

        Rejecting it loses the whole assessment over a decimal point — which
        is exactly what happened to two eval cases the first time the scorer
        was run against Gemini.
        """
        if isinstance(value, float):
            return round(value)
        return value
    verdict: Verdict
    rationale: str

    # Whether the ad is for a role on target_roles at all. Across eleven
    # recorded applications this predicted the outcome better than the
    # requirement match did: the only one that drew a considered human
    # response was the only one aimed at a listed target role.
    target_role_match: bool
    target_role_note: str

    constraints: list[ConstraintCheck] = Field(default_factory=list)
    requirements: list[RequirementMatch] = Field(default_factory=list)
    emphasise: list[str] = Field(default_factory=list)
    challenge_points: list[ChallengePoint] = Field(default_factory=list)
    profile_gaps: list[str] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list)

    model_used: str | None = None
    scored_at: datetime

    @property
    def unmet(self) -> list[RequirementMatch]:
        return [r for r in self.requirements if r.status is MatchStatus.gap]

    @property
    def breaches(self) -> list[ConstraintCheck]:
        return [c for c in self.constraints if c.status is ConstraintStatus.breach]

    @property
    def unknowns(self) -> list[ConstraintCheck]:
        return [c for c in self.constraints if c.status is ConstraintStatus.unknown]


# --------------------------------------------------------------------------- #
# The application pipeline (Phase 5)
# --------------------------------------------------------------------------- #


class ApplicationStatus(str, Enum):
    """How far an application got, in order.

    One vocabulary, not two. The eval harness had its own `Outcome` enum and
    the pipeline was specified with a separate status enum covering the same
    ground; a translation layer between them would have been pure cost, and
    the first disagreement between the two lists would have been a bug nobody
    could see.

    `applied` is the live state — sent, nothing back yet. `applied_no_reply`
    is the terminal one: enough time has passed to call it ghosted. Only the
    second is a result.
    """

    identified = "identified"
    applied = "applied"
    applied_no_reply = "applied_no_reply"
    rejected_screen = "rejected_screen"
    recruiter_call = "recruiter_call"
    interview_1 = "interview_1"
    interview_2 = "interview_2"
    offer = "offer"
    withdrew = "withdrew"
    not_applied = "not_applied"


class Worth(str, Enum):
    """Was the day well spent, knowing what he knows now.

    Deliberately separate from the status. Alan was offered the Easy Signs job
    and it was still not worth applying for — the commute that ended it is an
    absolute filter in his own profile. The scorer is graded against this, not
    against whether the employer said yes.
    """

    yes = "yes"
    no = "no"
    unsure = "unsure"


class Application(_Base):
    """One application, and what became of it."""

    id: int | None = None
    jd_id: int
    status: ApplicationStatus = ApplicationStatus.identified
    applied_on: date | None = None
    # How it reached him: "seek", "linkedin", "recruiter — <name>", "referral".
    # Across fourteen recorded applications this predicted the outcome better
    # than the requirement match did.
    channel: str | None = None
    notes: str = ""

    # The eval label. Set when it is knowable, which is usually later.
    worth_applying: Worth = Worth.unsure
    worth_why: str = ""
    # True while the judgment is a reading of Alan's notes rather than his
    # statement. Set on import, cleared the moment he sets --worth himself.
    # The report counts these separately: a metric must never be quoted as his
    # judgment when it is someone else's inference.
    worth_derived: bool = False

    # Set when Alan generated documents against a `skip` verdict. The scorer's
    # four disagreements across the first fourteen cases were all in one
    # direction — it said skip where he judged the role worth applying to —
    # and the way to find out who is right is to record the overrides and see
    # what becomes of them, not to tune the prompt on fourteen cases and one
    # retrospective opinion.
    overrode_scorer: bool = False

    updated_at: datetime


# --------------------------------------------------------------------------- #
# Interview preparation (Phase 7)
# --------------------------------------------------------------------------- #


class PrepQuestion(_Base):
    """One question to expect, and what to answer it with.

    ``story_ref`` points at the story bank. A question with no story behind it
    is worth knowing about — it is a question Alan can only answer in the
    abstract, which is exactly the one to prepare hardest.
    """

    question: str
    why_asked: str
    story_ref: str | None = None
    answer_outline: str
    # Questions carried over from the assessment's challenge_points. They are
    # not predictions: they are the objections the scorer already found in the
    # gap between this ad and the profile.
    hard: bool = False


class InterviewPrep(_Base):
    jd_id: int
    interviewers: list[str] = Field(default_factory=list)
    questions: list[PrepQuestion] = Field(default_factory=list)
    # What Alan asks them. Seeded from the assessment's unresolved filters —
    # an unanswered commute or salary question is the interview's real agenda.
    questions_to_ask: list[str] = Field(default_factory=list)
    opening: str = ""
    prepared_at: datetime
