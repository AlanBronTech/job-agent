"""Where generated documents land on disk.

One folder per application, holding everything that was produced for it:

    ~/job-agent-out/2026-09_Toshiba_EngineeringManager/
        AlanBron_Resume_Toshiba_202609.docx
        AlanBron_CoverLetter_Toshiba_202609.docx
        answers.md
        assessment.md
        job-ad.md

Google Drive upload was dropped on 2026-09-01 in favour of this — the folder
is copied by hand when it suits. `assessment.md` is written alongside so that
months later it is possible to see *why* a resume was cut the way it was, and
so the eval harness has the pairing.

`job-ad.md` is written from the stored `raw_text` rather than copied from the
saved PDF. Nothing in the store records where that PDF was, and it may have
been moved or deleted by the time anyone looks; more usefully, `raw_text` is
exactly what the parser and the scorer read, so a document that came out
strangely can be checked against the text that produced it rather than
against the page a human saw.
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


def job_ad_markdown(jd: JobDescription) -> str:
    """The advertisement as the tool read it, with what was parsed out of it."""
    lines = [
        f"# {jd.title}" + (f" · {jd.company}" if jd.company else ""),
        "",
    ]

    facts: list[tuple[str, str]] = []
    if jd.company:
        facts.append(("Company", jd.company))
    if jd.posted_by and jd.posted_by != jd.company:
        facts.append(("Posted by", jd.posted_by + (" (agency)" if jd.via_agency else "")))
    if jd.location:
        facts.append(("Location", jd.location))
    facts.append(("Work", f"{jd.work_type.value}, {jd.work_arrangement.value}"))
    facts.append(("Seniority", jd.seniority.value))
    if jd.salary_range:
        facts.append(("Salary", _salary(jd)))
    if jd.source:
        facts.append(("Source", jd.source))
    if jd.source_metadata:
        facts.append(("Posting", jd.source_metadata))
    if jd.source_url:
        facts.append(("URL", jd.source_url))
    facts.append(("Ingested", f"{jd.ingested_at:%Y-%m-%d}"))

    lines += [f"**{label}:** {value}  " for label, value in facts]

    for heading, items in (
        ("Must haves", jd.must_haves),
        ("Nice to haves", jd.nice_to_haves),
        ("Responsibilities", jd.responsibilities),
        ("Red flags", jd.red_flags),
    ):
        if items:
            lines += ["", f"## {heading}", ""]
            lines += [f"- {item}" for item in items]

    if jd.tech_stack:
        lines += ["", "## Tech stack", "", ", ".join(jd.tech_stack)]

    lines += [
        "",
        "## The advertisement",
        "",
        "As read by the parser — the text every downstream claim was checked",
        "against, kept verbatim.",
        "",
        "```",
        jd.raw_text.strip(),
        "```",
        "",
    ]
    return "\n".join(lines)


def _salary(jd: JobDescription) -> str:
    salary = jd.salary_range
    if salary is None:
        return "not stated"
    if salary.min_aud or salary.max_aud:
        low = f"${salary.min_aud:,}" if salary.min_aud else "?"
        high = f"${salary.max_aud:,}" if salary.max_aud else "?"
        suffix = ""
        if salary.includes_super is True:
            suffix = " inc. super"
        elif salary.includes_super is False:
            suffix = " + super"
        return f"{low} – {high}{suffix}"
    return salary.raw or "not stated"


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
