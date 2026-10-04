"""What a workflow hands back when it ran.

Facts, not presentation, for the same reason as `refusals`. `warnings` holds
the non-fatal things the CLI has always said in passing ("scored, but could
not save", "could not record the override"): bookkeeping that must never stop
the work, and must never be silent either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jobagent.core.generate import UnusedEntry
from jobagent.core.models import (
    CompanyHistory,
    FitAssessment,
    InterviewPrep,
    JobDescription,
    Verdict,
)
from jobagent.core.validation import ValidationIssue


@dataclass
class AddResult:
    jd: JobDescription
    history: CompanyHistory | None
    # Set when the saved page held so little text it is probably a collapsed
    # description. Not a refusal: a short ad can be genuinely short.
    thin_chars: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    jd: JobDescription
    assessment: FitAssessment
    history: CompanyHistory | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class GeneratePlan:
    """What a generate run would do. Computed without spending anything."""

    jd: JobDescription
    verdict: Verdict
    rationale: str
    needs_overrule: bool
    folder: Path
    names: list[str]
    clashes: list[tuple[str, datetime]]
    history: CompanyHistory | None = None
    # services.reapply's Clear / SameJob / PossiblySame, for the confirm page.
    reapply: object | None = None


@dataclass
class GenerateResult:
    folder: Path
    written: list[Path]
    issues: list[ValidationIssue]
    unused: list[UnusedEntry]
    superseded: Path | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class PrepResult:
    prep: InterviewPrep
    issues: list[ValidationIssue]
    written: Path | None = None
