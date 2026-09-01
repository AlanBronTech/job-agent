"""Where generated documents land on disk.

One folder per application, holding everything that was produced for it:

    ~/job-agent-out/2026-09_Toshiba_EngineeringManager/
        AlanBron_Resume_Toshiba_202609.docx
        AlanBron_CoverLetter_Toshiba_202609.docx
        answers.md
        assessment.md

Google Drive upload was dropped on 2026-09-01 in favour of this — the folder
is copied by hand when it suits. `assessment.md` is written alongside so that
months later it is possible to see *why* a resume was cut the way it was, and
so the eval harness has the pairing.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from jobagent.core.models import ConstraintStatus, FitAssessment, JobDescription
from jobagent.core.validation import ValidationIssue

_UNSAFE = re.compile(r"[^A-Za-z0-9]+")


class DocsError(Exception):
    """The output folder could not be prepared or written to."""


def application_folder(
    output_dir: Path, jd: JobDescription, *, when: date | None = None
) -> Path:
    """The folder for one application. Created if absent."""
    when = when or date.today()
    name = f"{when:%Y-%m}_{_slug(jd.company or jd.posted_by or 'Unknown')}_{_slug(jd.title)}"
    folder = Path(output_dir).expanduser() / name
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DocsError(f"Could not create {folder}: {exc}") from exc
    return folder


def document_name(kind: str, jd: JobDescription, *, when: date | None = None) -> str:
    """`AlanBron_Resume_Toshiba_202609.docx`."""
    when = when or date.today()
    company = _slug(jd.company or jd.posted_by or "Unknown")
    return f"AlanBron_{kind}_{company}_{when:%Y%m}.docx"


def write_text(folder: Path, filename: str, text: str) -> Path:
    path = folder / filename
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise DocsError(f"Could not write {path}: {exc}") from exc
    return path


def assessment_markdown(
    assessment: FitAssessment, jd: JobDescription, issues: list[ValidationIssue]
) -> str:
    """The assessment as a readable record, kept with the documents it shaped."""
    lines = [
        f"# {jd.title}" + (f" · {jd.company}" if jd.company else ""),
        "",
        f"**Verdict:** {assessment.verdict.value.replace('_', ' ')}  ",
        f"**Score:** {assessment.overall_score}/100 hiring manager · "
        f"{assessment.recruiter_screen_score}/100 recruiter screen  ",
        f"**Target role:** {'yes' if assessment.target_role_match else 'no'} — "
        f"{assessment.target_role_note}  ",
        f"**Scored:** {assessment.scored_at:%Y-%m-%d} using "
        f"{assessment.model_used or 'an unrecorded model'}",
        "",
        assessment.rationale,
        "",
    ]

    if jd.source_url:
        lines += [f"Ad: {jd.source_url}", ""]

    lines += ["## Hard filters", ""]
    mark = {
        ConstraintStatus.ok: "ok",
        ConstraintStatus.breach: "**BREACH**",
        ConstraintStatus.unknown: "**unknown**",
    }
    for check in assessment.constraints:
        lines.append(f"- {check.name}: {mark[check.status]} — {check.detail}")

    if assessment.questions_to_ask:
        lines += ["", "## Ask before applying", ""]
        lines += [f"- {question}" for question in assessment.questions_to_ask]

    lines += ["", "## Requirements", ""]
    for match in assessment.requirements:
        reference = f" ({match.evidence_ref})" if match.evidence_ref else ""
        lines.append(f"- **{match.status.value}** — {match.requirement}")
        lines.append(f"  - {match.note}{reference}")

    if assessment.emphasise:
        lines += ["", "## Lead with", ""]
        lines += [
            f"{index}. {item}" for index, item in enumerate(assessment.emphasise, 1)
        ]

    if assessment.challenge_points:
        lines += ["", "## They will push on", ""]
        for challenge in assessment.challenge_points:
            lines.append(f"- **{challenge.point}**")
            lines.append(f"  - {challenge.response}")

    if assessment.profile_gaps:
        lines += ["", "## Gaps in the profile itself", ""]
        lines += [f"- {gap}" for gap in assessment.profile_gaps]

    if issues:
        lines += ["", "## Validation issues raised at generation", ""]
        for issue in issues:
            lines.append(f"- **{issue.severity.value}** {issue.rule}: {issue.detail}")
            if issue.excerpt:
                lines.append(f"  - `{issue.excerpt}`")

    return "\n".join(lines) + "\n"


def _slug(value: str) -> str:
    """`Toshiba Global Commerce Solutions (TGCS)` -> `ToshibaGlobalCommerce`.

    Capped, because the folder name carries company *and* title and a long
    pair produces a path nobody can read in a terminal.
    """
    words = [word for word in _UNSAFE.split(value) if word]
    out = ""
    for word in words:
        candidate = out + word[:1].upper() + word[1:]
        if len(candidate) > 28:
            break
        out = candidate
    return out or "Unknown"
