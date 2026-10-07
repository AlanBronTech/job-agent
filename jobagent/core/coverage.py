"""Every evidenced must-have on the resume, not only in the letter (spec 003, US2).

The scorer already did the mapping: each `requirements[]` row it marked `met`
or `partial` carries an `evidence_ref`. Coverage reads that rather than asking
a model again. The resume covers a requirement when a CAREER HIGHLIGHT or a
role bullet cites that evidence: the ref itself, its entry, a bullet within
it, or (for a story) a bullet linked to that story. A screener may read only
the resume; the worked example's best coaching evidence was in the letter.

A row with no evidence is a gap, reported as now and never filled. A row whose
evidence the role kind excludes is not demanded. A ref this module cannot
resolve to anything on a resume (a differentiator, say) is reported as not
checkable rather than blocked: a checker narrower than the evidence would
report the model's best answer as a defect.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jobagent.core import roles as kinds
from jobagent.core.models import FitAssessment, MatchStatus, Profile
from jobagent.core.validation import Severity, ValidationIssue

COVERED = "covered"
WEAK = "weak"
MISSING = "missing"
GAP = "gap"
UNCHECKED = "not checkable"


@dataclass
class CoverageRow:
    requirement: str
    evidence_ref: str | None
    status: str
    where: list[str] = field(default_factory=list)


def must_cover(
    assessment: FitAssessment, excluded: set[str] = frozenset()
) -> list[tuple[str, str]]:
    """(requirement, evidence_ref) the resume has to carry."""
    return [
        (row.requirement, row.evidence_ref)
        for row in assessment.requirements
        if row.status in (MatchStatus.met, MatchStatus.partial)
        and row.evidence_ref
        and not kinds.is_excluded(row.evidence_ref, excluded)
    ]


def coverage(
    assessment: FitAssessment,
    profile: Profile,
    cited: list[str],
    *,
    skills_text: str = "",
    excluded: set[str] = frozenset(),
) -> list[CoverageRow]:
    """One row per requirement. `cited` holds highlight and role-bullet refs."""
    resolvable = _resolvable_ids(profile)
    linked = _linked_stories(profile)
    rows: list[CoverageRow] = []
    for row in assessment.requirements:
        ref = row.evidence_ref
        if row.status is MatchStatus.gap or not ref:
            rows.append(CoverageRow(row.requirement, ref, GAP))
            continue
        if kinds.is_excluded(ref, excluded):
            continue
        if ref not in resolvable and ref.split(".", 1)[0] not in resolvable:
            rows.append(CoverageRow(row.requirement, ref, UNCHECKED))
            continue
        where = list(dict.fromkeys(c for c in cited if _answers(ref, c, linked)))
        if where:
            rows.append(CoverageRow(row.requirement, ref, COVERED, where))
        elif _in_skills(row.requirement, skills_text):
            rows.append(CoverageRow(row.requirement, ref, WEAK))
        else:
            rows.append(CoverageRow(row.requirement, ref, MISSING))
    return rows


def issues(rows: list[CoverageRow]) -> list[ValidationIssue]:
    out = []
    for row in rows:
        if row.status == MISSING:
            out.append(
                ValidationIssue(
                    rule="must-have missing",
                    severity=Severity.blocker,
                    detail=(
                        f"The ad asks for {row.requirement!r} and the profile "
                        f"evidences it ({row.evidence_ref}), but no highlight or "
                        "bullet on the resume cites that evidence."
                    ),
                    excerpt=row.evidence_ref,
                )
            )
        elif row.status == WEAK:
            out.append(
                ValidationIssue(
                    rule="covered weakly",
                    severity=Severity.warning,
                    detail=(
                        f"{row.requirement!r} is answered on the resume only by a "
                        f"skills keyword; the evidence ({row.evidence_ref}) is not cited."
                    ),
                    excerpt=row.evidence_ref,
                )
            )
    return out


def _answers(ref: str, cited: str, linked: dict[str, str]) -> bool:
    if cited == ref:
        return True
    if cited.split(".", 1)[0] == ref:  # a bullet within the cited entry
        return True
    if ref.split(".", 1)[0] == cited:  # a highlight citing the whole entry
        return True
    return linked.get(cited) == ref  # a bullet telling the cited story


def _resolvable_ids(profile: Profile) -> set[str]:
    ids = {story.id for story in profile.stories.stories}
    r = profile.roles
    for group in (r.roles, r.founder_track_record, r.ai_capability, r.earlier_career):
        ids.update(entry.id for entry in group)
    return ids


def _linked_stories(profile: Profile) -> dict[str, str]:
    r = profile.roles
    out = {}
    for group in (r.roles, r.founder_track_record, r.ai_capability):
        for entry in group:
            for index, bullet in enumerate(entry.bullets):
                if bullet.linked_story:
                    out[f"{entry.id}.{index}"] = bullet.linked_story
    return out


def _in_skills(requirement: str, skills_text: str) -> bool:
    if not skills_text:
        return False
    req = requirement.casefold()
    return any(
        len(skill) > 2 and skill in req
        for skill in (s.strip().casefold() for s in skills_text.split(","))
    )
