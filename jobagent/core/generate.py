"""Producing a tailored resume, cover letter and application answers.

The rule that shapes this module is CLAUDE.md's second hard rule: no invented
experience. It is enforced structurally rather than requested politely.

**For the resume, the model returns references, not prose.** It chooses which
roles appear, which bullets within them, in what order, and which skill
categories lead — by id. The text of every bullet is then copied verbatim out
of ``profile/``. A model that cannot type a bullet cannot embellish one, and
an id it invents fails a lookup instead of reaching the page.

The model does write prose in three places, because there is no honest way to
avoid it: the tagline, the two PROFILE paragraphs, and the cover letter. Those
go through ``core.validation``, which checks every number against the profile
and every phrase against ``voice.md``.

Dates are computed here, not asked for: ``roles.yaml`` stores ``YYYY-MM`` and
the resume shows years only, with the current role as "2026 – Present". That is
the age-signal policy's one mechanical part, and a model should not be trusted
with an arithmetic rule that Alan is deliberately exposed on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field, ValidationError

from jobagent.adapters.docx_writer import (
    CoverLetterContent,
    ResumeContent,
    RoleBlock,
    SkillCategory,
)
from jobagent.adapters.llm import LLMClient, LLMError
from jobagent.core.models import (
    FitAssessment,
    JobDescription,
    Profile,
    Visibility,
)
from jobagent.core.prompts import PromptError, load_prompt
from jobagent.core.validation import (
    Severity,
    ValidationIssue,
    validate_prose,
    validate_rendered,
)

RESUME_PROMPT = "generate_resume"
COVER_PROMPT = "generate_cover_letter"
ANSWERS_PROMPT = "generate_answers"

MAX_TOKENS = 8192

# voice.md: "Under 350 words. One page."
COVER_LETTER_MAX_WORDS = 350

# CLAUDE.md, hard rule 4: "If a draft contains banned phrases, regenerate."
# One retry, with the specific failures named. A second retry has not been
# worth it in practice — a model that misses twice is missing something the
# prompt does not say, and the issues are reported to Alan either way.
REWRITE_ATTEMPTS = 1

PRESENT = "present"


class GenerateError(Exception):
    """The document could not be generated."""


# --------------------------------------------------------------------------- #
# What the model is contracted to return
# --------------------------------------------------------------------------- #


class _RoleSelection(BaseModel):
    role_id: str
    bullet_refs: list[str] = Field(default_factory=list)


class _Highlight(BaseModel):
    label: str
    text: str
    source_ref: str


class _ResumeSelection(BaseModel):
    tagline: str
    profile_paragraphs: list[str]
    highlights: list[_Highlight] = Field(default_factory=list)
    skill_categories: list[str] = Field(default_factory=list)
    roles: list[_RoleSelection] = Field(default_factory=list)
    earlier_career_ids: list[str] = Field(default_factory=list)


@dataclass
class GeneratedResume:
    content: ResumeContent
    issues: list[ValidationIssue] = field(default_factory=list)


@dataclass
class GeneratedText:
    text: str
    issues: list[ValidationIssue] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Resume
# --------------------------------------------------------------------------- #


def build_resume(
    jd: JobDescription,
    profile: Profile,
    assessment: FitAssessment,
    *,
    client: LLMClient,
    today: date | None = None,
) -> GeneratedResume:
    """Select and order profile content for one ad, and assemble the resume."""
    catalogue = build_catalogue(profile)
    selection = _ask_for_selection(jd, profile, assessment, catalogue, client=client)

    issues: list[ValidationIssue] = []
    for paragraph in [selection.tagline, *selection.profile_paragraphs]:
        issues += validate_prose(paragraph, profile, context="the PROFILE section")
    for highlight in selection.highlights:
        issues += validate_prose(
            f"{highlight.label} — {highlight.text}",
            profile,
            context="a CAREER HIGHLIGHTS bullet",
        )
        issues += _check_reference(highlight.source_ref, catalogue)

    content, reference_issues = _assemble(
        selection, profile, catalogue, today=today or date.today()
    )
    return GeneratedResume(content=content, issues=issues + reference_issues)


def _ask_for_selection(
    jd: JobDescription,
    profile: Profile,
    assessment: FitAssessment,
    catalogue: dict[str, str],
    *,
    client: LLMClient,
) -> _ResumeSelection:
    try:
        prompt = load_prompt(
            RESUME_PROMPT,
            jd_json=_jd_summary(jd),
            assessment_json=_assessment_summary(assessment),
            catalogue=_render_catalogue(profile, catalogue),
            skills=", ".join(profile.roles.skills),
            voice=profile.voice,
        )
    except PromptError as exc:
        raise GenerateError(str(exc)) from exc

    try:
        parsed, _ = client.complete_json(
            prompt=prompt, label=RESUME_PROMPT, max_tokens=MAX_TOKENS
        )
    except LLMError as exc:
        raise GenerateError(f"Model call failed while selecting content: {exc}") from exc

    try:
        return _ResumeSelection.model_validate(parsed)
    except ValidationError as exc:
        raise GenerateError(
            f"The model's selection did not match the contract.\n{exc}"
        ) from exc


def _assemble(
    selection: _ResumeSelection,
    profile: Profile,
    catalogue: dict[str, str],
    *,
    today: date,
) -> tuple[ResumeContent, list[ValidationIssue]]:
    """Turn the selection into rendered content, resolving every reference.

    A reference the model invented fails here rather than reaching the page.
    """
    issues: list[ValidationIssue] = []
    person = profile.roles.person
    roles_by_id = {role.id: role for role in profile.roles.roles}

    role_blocks: list[RoleBlock] = []
    for chosen in selection.roles:
        role = roles_by_id.get(chosen.role_id)
        if role is None:
            issues.append(_unknown(chosen.role_id, "role"))
            continue
        if role.visibility is Visibility.scorer_only:
            issues.append(
                ValidationIssue(
                    rule="scorer-only content",
                    severity=Severity.blocker,
                    detail=f"Role {role.id!r} is scorer_only and must not be rendered.",
                )
            )
            continue
        bullets = []
        for ref in chosen.bullet_refs:
            text = catalogue.get(ref)
            if text is None:
                issues.append(_unknown(ref, "bullet"))
                continue
            issues += validate_rendered(text, context=f"Bullet {ref}")
            bullets.append(text)
        role_blocks.append(
            RoleBlock(
                title=role.title,
                company=role.company,
                dates=format_dates(role.start, role.end, today=today),
                bullets=bullets,
            )
        )

    highlights = []
    for highlight in selection.highlights:
        highlights.append((highlight.label, highlight.text))

    skills = []
    for key in selection.skill_categories or list(profile.roles.skills):
        values = profile.roles.skills.get(key)
        if values is None:
            issues.append(_unknown(key, "skill category"))
            continue
        skills.append(SkillCategory(label=_skill_label(key), skills=", ".join(values)))

    earlier = []
    by_id = {entry.id: entry for entry in profile.roles.earlier_career}
    for entry_id in selection.earlier_career_ids:
        entry = by_id.get(entry_id)
        if entry is None:
            issues.append(_unknown(entry_id, "earlier career entry"))
            continue
        line = f"{entry.company} — {entry.summary}"
        issues += validate_rendered(line, context=f"Earlier-career entry {entry_id}")
        earlier.append(line)

    content = ResumeContent(
        name=person.name.upper(),
        tagline=selection.tagline,
        contact=_contact_line(profile),
        profile_paragraphs=selection.profile_paragraphs,
        highlights=highlights,
        skills=skills,
        roles=role_blocks,
        earlier_career=earlier,
        education=_education_lines(profile),
    )
    return content, issues


# --------------------------------------------------------------------------- #
# Cover letter and answers
# --------------------------------------------------------------------------- #


def build_cover_letter(
    jd: JobDescription,
    profile: Profile,
    assessment: FitAssessment,
    *,
    client: LLMClient,
) -> GeneratedText:
    try:
        prompt = load_prompt(
            COVER_PROMPT,
            jd_json=_jd_summary(jd),
            assessment_json=_assessment_summary(assessment),
            catalogue=_render_catalogue(profile, build_catalogue(profile)),
            stories=_render_stories(profile),
            voice=profile.voice,
        )
    except PromptError as exc:
        raise GenerateError(str(exc)) from exc

    return _write_and_check(
        client,
        prompt,
        COVER_PROMPT,
        profile,
        max_words=COVER_LETTER_MAX_WORDS,
        context="The cover letter",
    )


def build_answers(
    questions: list[str],
    jd: JobDescription,
    profile: Profile,
    assessment: FitAssessment,
    *,
    client: LLMClient,
) -> GeneratedText:
    if not questions:
        raise GenerateError("No application questions were supplied.")
    try:
        prompt = load_prompt(
            ANSWERS_PROMPT,
            jd_json=_jd_summary(jd),
            assessment_json=_assessment_summary(assessment),
            catalogue=_render_catalogue(profile, build_catalogue(profile)),
            stories=_render_stories(profile),
            questions="\n".join(f"{n}. {q}" for n, q in enumerate(questions, 1)),
            voice=profile.voice,
        )
    except PromptError as exc:
        raise GenerateError(str(exc)) from exc

    return _write_and_check(
        client, prompt, ANSWERS_PROMPT, profile, context="The answers"
    )


def _write_and_check(
    client: LLMClient,
    prompt: str,
    label: str,
    profile: Profile,
    *,
    max_words: int | None = None,
    context: str,
) -> GeneratedText:
    """Write, validate, and regenerate once if the draft breaks a hard rule.

    The failures are named back to the model rather than described in general
    terms: "358 words against a 350-word limit" is actionable, "too long" is
    not. Whatever survives the retry is returned with its issues attached —
    the human sees them either way.
    """
    attempt_prompt = prompt
    text = ""
    issues: list[ValidationIssue] = []

    for attempt in range(REWRITE_ATTEMPTS + 1):
        text = _ask_for_text(client, attempt_prompt, label)
        issues = validate_prose(
            text, profile, max_words=max_words, context=context
        )
        failures = [issue for issue in issues if issue.severity is Severity.blocker]
        if not failures or attempt == REWRITE_ATTEMPTS:
            break
        attempt_prompt = f"{prompt}\n\n{_rewrite_instruction(failures)}"

    return GeneratedText(text=text, issues=issues)


def _rewrite_instruction(failures: list[ValidationIssue]) -> str:
    lines = [
        "## Your previous draft was rejected",
        "",
        "It broke these rules. Fix every one of them and write the piece again.",
        "Do not explain the changes, do not apologise, return only the rewritten",
        "text.",
        "",
    ]
    for issue in failures:
        lines.append(f"- {issue.rule}: {issue.detail}")
        if issue.excerpt:
            lines.append(f"  offending text: {issue.excerpt}")
    return "\n".join(lines)


def _ask_for_text(client: LLMClient, prompt: str, label: str) -> str:
    try:
        response = client.complete(prompt=prompt, label=label, max_tokens=MAX_TOKENS)
    except LLMError as exc:
        raise GenerateError(f"Model call failed while writing: {exc}") from exc
    text = response.text.strip()
    if not text:
        raise GenerateError("The model returned nothing.")
    return text


# --------------------------------------------------------------------------- #
# The profile, as references
# --------------------------------------------------------------------------- #


def build_catalogue(profile: Profile) -> dict[str, str]:
    """Every renderable bullet, keyed by a stable reference.

    ``easy_signs.0``, ``home_design_directory.1``. Entries marked
    ``scorer_only`` are absent: they inform a decision and are never rendered.
    """
    catalogue: dict[str, str] = {}
    roles = profile.roles
    groups = (roles.roles, roles.founder_track_record, roles.ai_capability)
    for group in groups:
        for entry in group:
            if entry.visibility is Visibility.scorer_only:
                continue
            for index, bullet in enumerate(entry.bullets):
                catalogue[f"{entry.id}.{index}"] = bullet.text
    return catalogue


def _render_catalogue(profile: Profile, catalogue: dict[str, str]) -> str:
    """The catalogue as text for the prompt, grouped so the model can see
    which bullets belong to which role."""
    lines: list[str] = []
    roles = profile.roles

    lines.append("## Roles (EXPERIENCE section)")
    for role in roles.roles:
        if role.visibility is Visibility.scorer_only:
            continue
        lines.append(f"\n{role.id} — {role.title} · {role.company} ({role.sector})")
        for index, bullet in enumerate(role.bullets):
            lines.append(
                f"  {role.id}.{index}  [{bullet.evidence_strength.value}] "
                f"{bullet.text}"
            )

    lines.append("\n## Founder track record")
    for entry in roles.founder_track_record:
        if entry.visibility is Visibility.scorer_only:
            continue
        lines.append(f"\n{entry.id} — {entry.role}, {entry.company}")
        for index, bullet in enumerate(entry.bullets):
            lines.append(f"  {entry.id}.{index}  {bullet.text}")

    lines.append("\n## AI capability")
    for entry in roles.ai_capability:
        if entry.visibility is Visibility.scorer_only:
            continue
        lines.append(f"\n{entry.id} — {entry.label}")
        for index, bullet in enumerate(entry.bullets):
            lines.append(f"  {entry.id}.{index}  {bullet.text}")

    lines.append("\n## Earlier career (undated, one condensed line each)")
    for entry in roles.earlier_career:
        lines.append(f"  {entry.id} — {entry.company}: {entry.summary}")

    return "\n".join(lines)


def _render_stories(profile: Profile) -> str:
    lines = []
    for story in profile.stories.stories:
        lines.append(
            f"{story.id} — {story.label}\n"
            f"  situation: {story.situation}\n"
            f"  action: {story.action}\n"
            f"  result: {story.result}"
        )
    explanations = profile.stories.explanations.model_dump(exclude_none=True)
    if explanations:
        lines.append("\n## Agreed explanations — use these words, do not invent others")
        for key, value in explanations.items():
            if isinstance(value, str):
                lines.append(f"  {key}: {value}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Deterministic details
# --------------------------------------------------------------------------- #


def format_dates(start: str, end: str, *, today: date) -> str:
    """Years only, current role as "Present".

    ``roles.yaml`` stores ``YYYY-MM``; the resume shows ``2025 – 2026``. The
    truncation is the age-signal policy in mechanical form — the dates are
    shown, the span is never computed.
    """
    start_year = start.split("-")[0]
    if end.lower() == PRESENT:
        return f"{start_year} – Present"
    end_year = end.split("-")[0]
    if start_year == end_year:
        return start_year
    return f"{start_year} – {end_year}"


def _contact_line(profile: Profile) -> str:
    person = profile.roles.person
    parts = [person.location, person.phone, person.email]
    if person.linkedin:
        parts.append(person.linkedin)
    return "   ·   ".join(part for part in parts if part)


def _education_lines(profile: Profile) -> list[str]:
    """Certifications first, then degrees — the master's order."""
    person = profile.roles.person
    lines = [f"{cert.name} — {cert.issuer}" for cert in person.certifications]
    lines += [
        f"{entry.qualification} — {entry.institution}" for entry in person.education
    ]
    return lines


def _skill_label(key: str) -> str:
    return key.replace("_and_", " & ").replace("_", " ").upper()


def _jd_summary(jd: JobDescription) -> str:
    data = jd.model_dump(mode="json")
    data.pop("raw_text", None)
    import json

    return json.dumps(data, indent=2, ensure_ascii=False)


def _assessment_summary(assessment: FitAssessment) -> str:
    import json

    data = assessment.model_dump(mode="json")
    for key in ("id", "jd_id", "model_used", "scored_at", "constraints"):
        data.pop(key, None)
    return json.dumps(data, indent=2, ensure_ascii=False)


def _check_reference(ref: str, catalogue: dict[str, str]) -> list[ValidationIssue]:
    if ref in catalogue:
        return []
    return [_unknown(ref, "bullet")]


def _unknown(ref: str, kind: str) -> ValidationIssue:
    return ValidationIssue(
        rule="unknown reference",
        severity=Severity.blocker,
        detail=(
            f"The model referenced a {kind} {ref!r} that is not in the profile. "
            "Either the profile changed, or the reference was invented."
        ),
        excerpt=ref,
    )
