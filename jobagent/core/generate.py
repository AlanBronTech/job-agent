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

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from jobagent.adapters.docx_writer import (
    CoverLetterContent,
    ResumeContent,
    RoleBlock,
    SkillCategory,
)
from jobagent.adapters.llm import LLMClient, LLMError
from jobagent.core import coverage as cover
from jobagent.core import roles as kinds
from jobagent.core.models import (
    EvidenceStrength,
    FounderEntry,
    FitAssessment,
    JobDescription,
    Profile,
    RoleClassification,
    Visibility,
)
from jobagent.core.prompts import PromptError, load_prompt
from jobagent.core.validation import (
    Severity,
    ValidationIssue,
    check_citations,
    check_employers,
    check_resume_reuse,
    check_story_reuse,
    check_third_person,
    story_of,
    story_uses,
    validate_prose,
    validate_rendered,
)

RESUME_PROMPT = "generate_resume"
COVER_PROMPT = "generate_cover_letter"
CONTEXT_PROMPT = "context"
CONTRACT_PROMPT = "contract_writing"
# A contract's letter is shorter than a permanent one (350), not a stub: at
# 120 words the JD 90 letter was cut to three thin paragraphs and dropped the
# AI work the ad was about (Alan, 2026-10-22).
CONTRACT_NOTE_MAX_WORDS = 220
REVISION_PROMPT = "revision"
ANSWERS_PROMPT = "generate_answers"

# Letters and answers. Raised from 8,192 on 2026-10-14: with the cited-sentence
# contract both real letters that day ran out on the model's reasoning, which
# counts as output, before the JSON was finished.
MAX_TOKENS = 32768

# The resume selection gets its own, larger budget. A correct answer to that
# contract is under a thousand tokens — references, eight keys, a tagline and
# two paragraphs — but on 2026-09-04 the Colonial First State generation ran
# to the full 8,192 and was truncated, losing the call. The prompt already
# bounds the verbosity (rules 1, 3, 5, 6 and 10 all cap counts), so the
# ceiling is there to survive a model that derails, not to shape the output.
# Same reasoning as MAX_TOKENS in core/scoring.py, and the same number.
#
# Raised to 32,768 on 2026-10-07. The output count includes the model's own
# reasoning, which the adapter does not switch off, and on this prompt it had
# climbed run by run: 5.8k, 7.6k, 8.9k, 12.0k tokens for a JSON answer of
# about one thousand. With spec 003's must-cover list and reuse caps added it
# reached the 16,384 ceiling on the first real 003 regenerate and the paid call was
# lost. The ceiling still exists to stop a derailed answer, not to shape one.
RESUME_MAX_TOKENS = 32768

# voice.md: "Under 350 words. One page."
COVER_LETTER_MAX_WORDS = 350


@dataclass(frozen=True)
class ResumeLength:
    """How long a resume should render, in pages (Alan, 2026-10-23).

    `low`..`high` is the target; `limit` is the most that may go out, and a
    resume over it is a blocker. Measured after rendering
    (`adapters/pages.py`), because only a layout engine knows.
    """

    low: float
    high: float
    limit: float
    rule: str


FULL_TIME_LENGTH = ResumeLength(
    low=2.0, high=2.75, limit=3.0,
    rule=(
        "**About two and a half pages, never more than three.** That is roughly "
        "22-28 role bullets in total across all roles, plus the highlights. Cut, "
        "do not cram — a bullet that does not answer something in this ad is "
        "taking space from one that does."
    ),
)
CONTRACT_LENGTH = ResumeLength(
    low=1.5, high=1.75, limit=1.75,
    rule=(
        "**A contractor CV: one and a half to one and three-quarter pages.** A "
        "contractor is bought for a specific piece of work, so this is shorter "
        "than a permanent resume. Roughly 10-14 role bullets in total: two or "
        "three for the roles that evidence this contract, one for the rest. "
        "Choose at most three `earlier_career_ids`, the most relevant. Cut "
        "everything that does not answer this ad."
    ),
)


def resume_length(contract: bool) -> ResumeLength:
    return CONTRACT_LENGTH if contract else FULL_TIME_LENGTH

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

    @field_validator("source_ref", mode="before")
    @classmethod
    def _one_ref(cls, value: object) -> object:
        """A highlight cites one source; a list of bullets of one entry is that entry.

        The model sent `["datallama.0", "datallama.1"]` for a DataLlama
        highlight and the whole resume was lost on a type error after the
        tokens were paid for (JD 89, 2026-10-22). Bullets of a single entry
        become the entry id, which a highlight may cite; refs from different
        entries keep the first, so the citation is still checked.
        """
        if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            heads = {v.split(".", 1)[0] for v in value}
            return heads.pop() if len(heads) == 1 and len(value) > 1 else value[0]
        return value


class _ResumeSelection(BaseModel):
    tagline: str
    profile_paragraphs: list[str]
    # The ids each PROFILE paragraph draws on, one list per paragraph. Lets the
    # story-reuse cap see the paragraph as well as the highlights and bullets.
    profile_refs: list[list[str]] = Field(default_factory=list)
    highlights: list[_Highlight] = Field(default_factory=list)
    skill_categories: list[str] = Field(default_factory=list)
    roles: list[_RoleSelection] = Field(default_factory=list)
    earlier_career_ids: list[str] = Field(default_factory=list)


class Sentence(BaseModel):
    """One sentence of a letter or answer, with the evidence it rests on.

    `cites` holds profile ids, or "ad" for a sentence about the ad or the
    employer. `quote` is the ad's own words behind a company sentence.
    Stray keys are dropped rather than failing the call (CLAUDE.md).
    """

    model_config = ConfigDict(extra="ignore")

    text: str
    cites: list[str] = Field(default_factory=list)
    quote: str | None = None


class _Letter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    paragraphs: list[list[Sentence]]


@dataclass(frozen=True)
class UnusedEntry:
    """A profile entry the model was shown and then used nowhere.

    Reported, never enforced. Which evidence an ad rewards is the model's
    judgement and usually it is right — the point is that the judgement should
    be visible while the documents are still being reviewed, not inferred
    afterwards from a resume that has already been sent.
    """

    id: str
    group: str
    label: str
    strong: bool
    highlight_only: bool


@dataclass
class GeneratedResume:
    content: ResumeContent
    issues: list[ValidationIssue] = field(default_factory=list)
    unused: list[UnusedEntry] = field(default_factory=list)
    coverage: list[cover.CoverageRow] = field(default_factory=list)
    # Text already on the page, by ref: what the letter must not repeat.
    on_page: dict[str, str] = field(default_factory=dict)
    # The blockers of each draft that was rejected and written again, in
    # order. A rewrite doubles the time and cost of a document, and the
    # final issues alone cannot say why one happened.
    rejected: list[list[ValidationIssue]] = field(default_factory=list)
    # The prose the model wrote — each PROFILE paragraph and highlight — with
    # what it cites, for the claim check. Bullets are copied, so not here.
    sentences: list[Sentence] = field(default_factory=list)


@dataclass
class GeneratedText:
    text: str
    issues: list[ValidationIssue] = field(default_factory=list)
    # The cited sentences behind `text`, by paragraph (letters, spec 003).
    paragraphs: list[list[Sentence]] = field(default_factory=list)
    # As GeneratedResume.rejected.
    rejected: list[list[ValidationIssue]] = field(default_factory=list)

    @property
    def sentences(self) -> list[Sentence]:
        return [sentence for paragraph in self.paragraphs for sentence in paragraph]


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
    kind: RoleClassification | None = None,
    instructions: str | None = None,
    feedback: str | None = None,
    length: ResumeLength = FULL_TIME_LENGTH,
) -> GeneratedResume:
    """Select and order profile content for one ad, and assemble the resume.

    With a role kind, evidence excluded for it is left out of what the model
    is shown, and any reference to it in the answer is still a blocker.
    `instructions` is Alan's context and revision note (`instructions_block`),
    sent with every attempt; a rejected draft's failures follow it.
    `feedback` is the claim check's verdict on an earlier draft, sent the same way.
    """
    instructions = "\n\n".join(part for part in (instructions, feedback) if part) or None
    excluded = kinds.excluded_ids(profile, kinds.kinds_of(kind), jd)
    catalogue = build_catalogue(profile, excluded)
    citable = build_citable(profile, excluded)
    retry_note = None
    built: GeneratedResume | None = None
    rejected: list[list[ValidationIssue]] = []
    # A blocker is a stop, not a note (2026-10-15): the selection is asked for
    # again once with the failures named, as the letter always was. Whatever
    # survives the retry is returned with its issues, and the caller marks the
    # file NOT READY.
    for attempt in range(REWRITE_ATTEMPTS + 1):
        selection = _ask_for_selection(
            jd, profile, assessment, catalogue, client=client, kind=kind,
            excluded=excluded, retry_note=retry_note, instructions=instructions,
            length=length,
        )
        built = _check_resume(
            selection, jd, profile, assessment, catalogue, citable, excluded, kind,
            today=today or date.today(),
        )
        failures = [i for i in built.issues if i.severity is Severity.blocker]
        if not failures or attempt == REWRITE_ATTEMPTS:
            break
        rejected.append(failures)
        retry_note = _rewrite_instruction(failures, json_output=True)
    built.rejected = rejected
    return built


def _check_resume(
    selection, jd, profile, assessment, catalogue, citable, excluded, kind, *, today
) -> GeneratedResume:
    issues: list[ValidationIssue] = _uncited_paragraphs(selection)
    for paragraph in [selection.tagline, *selection.profile_paragraphs]:
        issues += validate_prose(paragraph, profile, context="the PROFILE section")
        # Solely about him, so "he" and "his" are third person too.
        issues += check_third_person(paragraph, "the PROFILE section", name=False, pronouns=True)
    for highlight in selection.highlights:
        issues += validate_prose(
            f"{highlight.label} — {highlight.text}",
            profile,
            context="a CAREER HIGHLIGHTS bullet",
        )
        if kinds.is_excluded(highlight.source_ref, excluded):
            issues.append(_excluded(highlight.source_ref, kind))
        else:
            issues += _check_citation(highlight.source_ref, citable)
    issues += _lead_issues(selection, profile, kind, assessment)
    issues += check_resume_reuse(story_uses(_resume_places(selection), profile))
    issues += _highlight_repeats(selection, catalogue)

    content, reference_issues = _assemble(
        selection,
        profile,
        catalogue,
        today=today,
        kind=kind,
        excluded=excluded,
    )
    cited = [h.source_ref for h in selection.highlights] + [
        ref for role in selection.roles for ref in role.bullet_refs
    ]
    rows = cover.coverage(
        assessment,
        profile,
        [ref for ref in cited if not kinds.is_excluded(ref, excluded)],
        skills_text=", ".join(category.skills for category in content.skills),
        excluded=excluded,
    )
    return GeneratedResume(
        content=content,
        issues=issues + reference_issues + cover.issues(rows),
        unused=unused_entries(selection, profile, excluded, on_page=_page_lines(content)),
        coverage=rows,
        on_page={
            **{f"highlight {n}": h.text for n, h in enumerate(selection.highlights, 1)},
            **{ref: catalogue[ref] for role in selection.roles
               for ref in role.bullet_refs if ref in catalogue},
        },
        sentences=resume_sentences(selection),
    )


def resume_sentences(selection: _ResumeSelection) -> list[Sentence]:
    """The resume's composed prose, each piece with the evidence it rests on.

    The JD 90 PROFILE (2026-10-22) claimed budget ownership and "on contract"
    work, and nothing checked it: the number check found no number, and the
    claim check only read letters. Bullets are copied verbatim and need no
    check; the tagline cites nothing and says too little to check.
    """
    refs = list(selection.profile_refs) + [[]] * len(selection.profile_paragraphs)
    out = [
        Sentence(text=paragraph, cites=list(refs[n]))
        for n, paragraph in enumerate(selection.profile_paragraphs)
    ]
    out += [
        Sentence(text=f"{h.label} — {h.text}", cites=[h.source_ref])
        for h in selection.highlights
    ]
    return out


def _uncited_paragraphs(selection: _ResumeSelection) -> list[ValidationIssue]:
    """A PROFILE paragraph that names no evidence cannot be claim-checked."""
    issues = []
    for n, paragraph in enumerate(selection.profile_paragraphs):
        if n >= len(selection.profile_refs) or not selection.profile_refs[n]:
            issues.append(
                ValidationIssue(
                    rule="uncited PROFILE paragraph",
                    severity=Severity.blocker,
                    detail=(
                        f"PROFILE paragraph {n + 1} lists no ids in profile_refs, so "
                        "nothing can check it against the profile. Name the ids it "
                        "draws on."
                    ),
                    excerpt=paragraph[:120],
                )
            )
    return issues


# A highlight and an experience bullet sharing this much of their wording is
# the same sentence twice on one page. Measured on the smaller text's words.
REPEAT_OVERLAP = 0.7


def _highlight_repeats(selection, catalogue: dict[str, str]) -> list[ValidationIssue]:
    """A CAREER HIGHLIGHT that restates a bullet printed below it.

    Both resumes of 2026-10-14 condensed a bullet into a highlight and kept
    the bullet in EXPERIENCE, so the reader met each claim twice in nearly the
    same words. A highlight must say something the experience section does
    not, or be worded so it does not read as a copy.
    """
    bullets = {ref: catalogue[ref] for role in selection.roles
               for ref in role.bullet_refs if ref in catalogue}
    issues = []
    for highlight in selection.highlights:
        for ref, text in bullets.items():
            if overlap(highlight.text, text) >= REPEAT_OVERLAP:
                issues.append(
                    ValidationIssue(
                        rule="highlight repeats a bullet",
                        severity=Severity.blocker,
                        detail=(
                            f"The highlight '{highlight.label}' restates bullet {ref}, "
                            "which is also in EXPERIENCE. Drop the bullet, cite other "
                            "evidence, or say what the bullet does not."
                        ),
                        excerpt=highlight.text[:120],
                    )
                )
                break
    return issues


def _ask_for_selection(
    jd: JobDescription,
    profile: Profile,
    assessment: FitAssessment,
    catalogue: dict[str, str],
    *,
    client: LLMClient,
    kind: RoleClassification | None = None,
    excluded: set[str] = frozenset(),
    retry_note: str | None = None,
    instructions: str | None = None,
    length: ResumeLength = FULL_TIME_LENGTH,
) -> _ResumeSelection:
    try:
        prompt = load_prompt(
            RESUME_PROMPT,
            jd_json=_jd_summary(jd),
            assessment_json=_assessment_summary(assessment),
            role_kind=role_kind_block(kind),
            lead_with="\n".join(f"{n}. {item}" for n, item in enumerate(assessment.emphasise, 1))
            or "(the assessment names no order)",
            must_cover=_must_cover_block(assessment, excluded),
            catalogue=_render_catalogue(profile, catalogue, excluded),
            skills=", ".join(profile.roles.skills),
            voice=profile.voice,
            length_rule=length.rule,
        )
    except PromptError as exc:
        raise GenerateError(str(exc)) from exc

    if instructions:
        prompt = f"{prompt}\n\n{instructions}"
    if retry_note:
        prompt = f"{prompt}\n\n{retry_note}"
    try:
        parsed, _ = client.complete_json(
            prompt=prompt, label=RESUME_PROMPT, max_tokens=RESUME_MAX_TOKENS
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
    kind: RoleClassification | None = None,
    excluded: set[str] = frozenset(),
) -> tuple[ResumeContent, list[ValidationIssue]]:
    """Turn the selection into rendered content, resolving every reference.

    A reference the model invented fails here rather than reaching the page.
    """
    issues: list[ValidationIssue] = []
    person = profile.roles.person
    roles_by_id = {role.id: role for role in profile.roles.roles}

    role_blocks: list[RoleBlock] = []
    for chosen in selection.roles:
        if kinds.is_excluded(chosen.role_id, excluded):
            issues.append(_excluded(chosen.role_id, kind))
            continue
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
            if kinds.is_excluded(ref, excluded):
                issues.append(_excluded(ref, kind))
                continue
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
    chosen_keys = selection.skill_categories or list(profile.roles.skills)
    for key in kinds.order_skills(chosen_keys, kind.primary if kind else None):
        values = profile.roles.skills.get(key)
        if values is None:
            issues.append(_unknown(key, "skill category"))
            continue
        skills.append(SkillCategory(label=_skill_label(key), skills=", ".join(values)))

    earlier = []
    by_id = {entry.id: entry for entry in profile.roles.earlier_career}
    founders_by_id = {entry.id: entry for entry in profile.roles.founder_track_record}
    for entry_id in selection.earlier_career_ids:
        if kinds.is_excluded(entry_id, excluded):
            issues.append(_excluded(entry_id, kind))
            continue
        entry = by_id.get(entry_id)
        if entry is not None:
            line = f"{entry.company} — {entry.summary}"
        else:
            founder = founders_by_id.get(entry_id)
            if founder is None:
                issues.append(_unknown(entry_id, "earlier career entry"))
                continue
            line, problem = _founder_line(founder)
            if problem is not None:
                issues.append(problem)
                continue
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


# A salutation the model wrote itself. Short, opens with "Dear" or "To", and
# ends at a comma or colon — a body sentence beginning "Dear" would not.
_SALUTATION = re.compile(r"^(dear|to)\b[^.]{0,60}[,:]$", re.IGNORECASE)
# Bare closings only. A line has to be nothing but the sign-off to match, so a
# sentence like "Thanks for contacting me." — which one real letter ends on —
# is left alone.
_SIGNOFF = re.compile(
    r"^(regards|kind regards|warm regards|best regards|sincerely|"
    r"yours (sincerely|faithfully)|best wishes|best|cheers|thanks|thank you)"
    r"\s*[,.]?$",
    re.IGNORECASE,
)


def strip_letter_salutation(text: str) -> str:
    """Drop a salutation the model supplied despite being told not to.

    `prompts/generate_cover_letter.md` says to return the body only, because
    the renderer writes the salutation from `CoverLetterContent`. The model
    obeyed on three of the first five letters; the other two came out addressed
    to the hiring manager twice, and one of those was for a role Alan had
    already applied to.

    A rule this mechanical is not worth asking for twice. Stripped before
    validation so the word count measures the body that will actually be
    rendered.
    """
    lines = text.lstrip().splitlines()
    while lines and _SALUTATION.match(lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).lstrip("\n")


def strip_letter_signoff(text: str, *, name: str | None = None) -> str:
    """Drop a closing the model supplied despite being told not to.

    The mirror of `strip_letter_salutation`, for the same reason and found the
    same way: the renderer writes the closing and the name from
    `CoverLetterContent`, so a model that also signs off produces a letter
    ending "Regards, Alan Bron" twice. One went to an employer before anyone
    noticed, because the very end of a document is the last place a reader
    looks — the salutation fix caught the top of the letter and nobody checked
    the bottom.

    Trailing blank lines, a bare sign-off and a line that is just Alan's name
    are dropped in any order until real content is reached. Only a *bare*
    sign-off matches: one letter's final sentence is "Thanks for contacting
    me.", and a rule loose enough to treat that as a closing would delete it.
    """
    lines = text.rstrip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()

    # A bare sign-off inside the last three lines ends the body, and everything
    # after it goes with it. Walking up one line at a time instead would stop at
    # whatever name the model signed: an unrecognised spelling blocked the strip
    # entirely and left the closing in place, which is how this was first
    # written and why a test caught it.
    for offset in range(1, min(3, len(lines)) + 1):
        if _SIGNOFF.match(lines[-offset].strip()):
            lines = lines[: -offset]
            break

    while lines:
        last = lines[-1].strip()
        if not last or (name and _is_name_line(last, name)):
            lines.pop()
        else:
            break
    return "\n".join(lines).rstrip("\n")


def _is_name_line(line: str, name: str) -> bool:
    """Whether a line is just the candidate's name, however it was decorated.

    One letter signed off `-- Alan Bron`, so the leading dashes have to go
    before comparing.
    """
    candidate = line.strip().lstrip("-–—*_ ").strip()
    return candidate.casefold() == name.strip().casefold()


def build_cover_letter(
    jd: JobDescription,
    profile: Profile,
    assessment: FitAssessment,
    *,
    client: LLMClient,
    kind: RoleClassification | None = None,
    feedback: str | None = None,
    on_resume: dict[str, str] | None = None,
    instructions: str | None = None,
    max_words: int = COVER_LETTER_MAX_WORDS,
) -> GeneratedText:
    """`feedback` is appended to the prompt: what a previous draft got wrong
    that only a later check could see (the paid claim check). `instructions`
    is Alan's context and revision note, ahead of it."""
    excluded = kinds.excluded_ids(profile, kinds.kinds_of(kind), jd)
    try:
        prompt = load_prompt(
            COVER_PROMPT,
            jd_json=_jd_summary(jd),
            assessment_json=_assessment_summary(assessment),
            role_kind=role_kind_block(kind),
            catalogue=_render_catalogue(profile, build_catalogue(profile, excluded), excluded),
            stories=_render_stories(profile, excluded),
            must_have_gaps="\n".join(f"- {g}" for g in must_have_gaps(jd, assessment))
            or "(none: write no gap sentence)",
            on_resume="\n".join(f"- [{ref}] {' '.join(text.split())}"
                                 for ref, text in (on_resume or {}).items())
            or "(no resume in this run)",
            voice=profile.voice,
        )
    except PromptError as exc:
        raise GenerateError(str(exc)) from exc
    if instructions:
        prompt = f"{prompt}\n\n{instructions}"
    if feedback:
        prompt = f"{prompt}\n\n{feedback}"

    return _write_cited(
        client,
        prompt,
        COVER_PROMPT,
        profile,
        known=known_citations(profile, excluded),
        max_words=max_words,
        context="The cover letter",
        ad_text=jd.raw_text,
        on_resume=on_resume or {},
    )


def build_answers(
    questions: list[str],
    jd: JobDescription,
    profile: Profile,
    assessment: FitAssessment,
    *,
    client: LLMClient,
    kind: RoleClassification | None = None,
    limit: int | None = None,
    instructions: str | None = None,
) -> "GeneratedAnswers":
    """One answer per question, short and long, each sentence cited (spec 003, US7).

    Starts from Alan's answer bank where it has an entry for the question's
    type. Checked in code: the character limit on every variant, the
    citations, each story told in one answer at most across the form, and a
    "why this company" answer citing only the ad (or his own bank entry).
    """
    if not questions:
        raise GenerateError("No application questions were supplied.")
    excluded = kinds.excluded_ids(profile, kinds.kinds_of(kind), jd)
    try:
        prompt = load_prompt(
            ANSWERS_PROMPT,
            jd_json=_jd_summary(jd),
            assessment_json=_assessment_summary(assessment),
            role_kind=role_kind_block(kind),
            catalogue=_render_catalogue(profile, build_catalogue(profile, excluded), excluded),
            stories=_render_stories(profile, excluded),
            answer_bank=_render_bank(profile),
            limit=f"{limit} characters" if limit else "none given; keep the long variant under 150 words",
            questions="\n".join(f"{n}. {q}" for n, q in enumerate(questions, 1)),
            voice=profile.voice,
        )
    except PromptError as exc:
        raise GenerateError(str(exc)) from exc
    if instructions:
        prompt = f"{prompt}\n\n{instructions}"

    known = known_citations(profile, excluded)
    attempt_prompt = prompt
    result = GeneratedAnswers(text="")
    rejected: list[list[ValidationIssue]] = []
    for attempt in range(REWRITE_ATTEMPTS + 1):
        try:
            parsed, _ = client.complete_json(
                prompt=attempt_prompt, label=ANSWERS_PROMPT, max_tokens=MAX_TOKENS
            )
            form = _Form.model_validate(parsed)
        except LLMError as exc:
            raise GenerateError(f"Model call failed while writing: {exc}") from exc
        except ValidationError as exc:
            raise GenerateError(f"The model's answers did not match the contract.\n{exc}") from exc
        result = _check_answers(form.answers, profile, known, limit)
        failures = [i for i in result.issues if i.severity is Severity.blocker]
        if not failures or attempt == REWRITE_ATTEMPTS:
            break
        rejected.append(failures)
        attempt_prompt = f"{prompt}\n\n{_rewrite_instruction(failures, json_output=True)}"
    result.rejected = rejected
    return result


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    type: str = "other"
    short: list[Sentence] = Field(default_factory=list)
    long: list[Sentence] = Field(default_factory=list)


class _Form(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: list[_Answer]


@dataclass
class GeneratedAnswers:
    text: str
    issues: list[ValidationIssue] = field(default_factory=list)
    answers: list = field(default_factory=list)
    rejected: list[list[ValidationIssue]] = field(default_factory=list)

    @property
    def sentences(self) -> list[Sentence]:
        return [s for a in self.answers for s in (*a.short, *a.long)]


# The answer types that may cite only the ad, or Alan's own words for them.
_COMPANY_TYPES = {"why_company": {"ad", "why_company"}}


def _check_answers(
    answers: list[_Answer], profile: Profile, known: set[str], limit: int | None
) -> GeneratedAnswers:
    issues: list[ValidationIssue] = []
    for n, answer in enumerate(answers, 1):
        context = f"Answer {n}"
        for variant in ("short", "long"):
            sentences = getattr(answer, variant)
            text = " ".join(s.text.strip() for s in sentences)
            if not text:
                issues.append(
                    ValidationIssue(
                        rule="missing variant",
                        severity=Severity.blocker,
                        detail=f"{context} has no {variant} variant.",
                        excerpt=answer.question,
                    )
                )
                continue
            issues += validate_prose(text, profile, context=f"{context} ({variant})")
            issues += check_citations([sentences], known, context=f"{context} ({variant})")
            issues += check_employers([sentences], profile)
            if limit and len(text) > limit:
                issues.append(
                    ValidationIssue(
                        rule="answer over limit",
                        severity=Severity.blocker,
                        detail=(
                            f"{context}'s {variant} variant is {len(text)} characters "
                            f"against a {limit}-character limit."
                        ),
                        excerpt=answer.question,
                    )
                )
        allowed = _COMPANY_TYPES.get(answer.type)
        if allowed:
            stray = {
                ref for s in (*answer.short, *answer.long) for ref in s.cites
            } - allowed
            if stray:
                issues.append(
                    ValidationIssue(
                        rule="company claim not from the ad",
                        severity=Severity.blocker,
                        detail=(
                            f"{context} is about the company and cites "
                            f"{', '.join(sorted(stray))}. Say only what the ad says, "
                            "or what Alan's own answer bank says."
                        ),
                        excerpt=answer.question,
                    )
                )
    issues += check_story_reuse(
        story_uses(
            [
                (f"answer {n}", [r for s in (*a.short, *a.long) for r in s.cites])
                for n, a in enumerate(answers, 1)
            ],
            profile,
        ),
        cap=1,
        context="The form's answers",
    )
    return GeneratedAnswers(text=answers_markdown(answers), issues=issues, answers=answers)


def answers_markdown(answers: list[_Answer]) -> str:
    """`answers.md`: each question, its type, then the short and long variants."""
    lines: list[str] = []
    for answer in answers:
        lines += [f"### {answer.question}", "", f"*{answer.type.replace('_', ' ')}*", ""]
        for variant in ("short", "long"):
            text = " ".join(s.text.strip() for s in getattr(answer, variant))
            lines += [f"**{variant.capitalize()}** ({len(text)} characters)", "", text, ""]
    return "\n".join(lines).rstrip() + "\n"


def _render_bank(profile: Profile) -> str:
    if not profile.stories.answers:
        return "(empty)"
    return "\n".join(
        f"{key.value}: {' '.join(text.split())}" for key, text in profile.stories.answers.items()
    )


def _write_and_check(
    client: LLMClient,
    prompt: str,
    label: str,
    profile: Profile,
    *,
    max_words: int | None = None,
    context: str,
    clean: Callable[[str], str] | None = None,
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
        if clean is not None:
            text = clean(text)
        issues = validate_prose(
            text, profile, max_words=max_words, context=context
        )
        failures = [issue for issue in issues if issue.severity is Severity.blocker]
        if not failures or attempt == REWRITE_ATTEMPTS:
            break
        attempt_prompt = f"{prompt}\n\n{_rewrite_instruction(failures)}"

    return GeneratedText(text=text, issues=issues)


def _write_cited(
    client: LLMClient,
    prompt: str,
    label: str,
    profile: Profile,
    *,
    known: set[str],
    max_words: int | None,
    context: str,
    ad_text: str | None = None,
    on_resume: dict[str, str] | None = None,
) -> GeneratedText:
    """Write as cited sentences, check them in code, regenerate once on blockers.

    The text is rebuilt from the sentences for rendering, so the .docx is the
    same shape as before. Furniture the model added anyway — a salutation, a
    bare sign-off, a line that is just the name — is dropped from the
    sentences before checking, as `strip_letter_*` drops it from prose.
    """
    attempt_prompt = prompt
    result = GeneratedText(text="")
    rejected: list[list[ValidationIssue]] = []
    name = profile.roles.person.name
    for attempt in range(REWRITE_ATTEMPTS + 1):
        try:
            parsed, _ = client.complete_json(
                prompt=attempt_prompt, label=label, max_tokens=MAX_TOKENS
            )
        except LLMError as exc:
            raise GenerateError(f"Model call failed while writing: {exc}") from exc
        try:
            letter = _Letter.model_validate(parsed)
        except ValidationError as exc:
            raise GenerateError(
                f"The model's sentences did not match the contract.\n{exc}"
            ) from exc
        paragraphs = _story_cites(_drop_furniture(letter.paragraphs, name), profile, known)
        text = paragraphs_text(paragraphs)
        if not text:
            raise GenerateError("The model returned nothing.")
        issues = validate_prose(text, profile, max_words=max_words, context=context)
        issues += check_citations(paragraphs, known, context=context)
        issues += check_employers(paragraphs, profile)
        issues += check_story_reuse(
            story_uses(
                [
                    (f"paragraph {n}", [ref for s in paragraph for ref in s.cites])
                    for n, paragraph in enumerate(paragraphs, 1)
                ],
                profile,
            ),
            cap=1,
            context=context,
        )
        if ad_text is not None:
            issues += check_company_sentences(paragraphs, ad_text)
        issues += _repeats_resume(paragraphs, on_resume or {})
        result = GeneratedText(text=text, issues=issues, paragraphs=paragraphs)
        failures = [issue for issue in issues if issue.severity is Severity.blocker]
        if not failures or attempt == REWRITE_ATTEMPTS:
            break
        rejected.append(failures)
        attempt_prompt = f"{prompt}\n\n{_rewrite_instruction(failures, json_output=True)}"
    result.rejected = rejected
    return result


def paragraphs_text(paragraphs: list[list[Sentence]]) -> str:
    return "\n\n".join(
        " ".join(sentence.text.strip() for sentence in paragraph) for paragraph in paragraphs
    )


def _story_cites(
    paragraphs: list[list[Sentence]], profile: Profile, known: set[str]
) -> list[list[Sentence]]:
    """`story_id.2` is the story, cited by a step of its sequence.

    Stories are not indexed the way role bullets are, but the first letter
    written after stories gained an ordered `sequence` cited
    `ai_tooling_rollout.0`. Read as an unknown id it failed four checks at
    once — unknown citation, wrong employer, no evidence, story reuse — for
    a sentence that was faithful to the story. Only a story id the writer was
    shown is accepted this way; anything else stays as written and fails.
    """
    stories = {story.id for story in profile.stories.stories} & known

    def fix(ref: str) -> str:
        head, _, index = ref.partition(".")
        return head if ref not in known and index.isdigit() and head in stories else ref

    return [
        [s.model_copy(update={"cites": list(dict.fromkeys(fix(r) for r in s.cites))}) for s in p]
        for p in paragraphs
    ]


def _drop_furniture(paragraphs: list[list[Sentence]], name: str) -> list[list[Sentence]]:
    """Drop a salutation, and a sign-off with whatever follows it.

    As `strip_letter_signoff`: a bare sign-off among the last three sentences
    ends the body, so a name it does not recognise goes with it.
    """
    flat = [(i, s) for i, paragraph in enumerate(paragraphs) for s in paragraph]
    cut = len(flat)
    for offset in range(1, min(3, len(flat)) + 1):
        if _SIGNOFF.match(flat[-offset][1].text.strip()):
            cut = len(flat) - offset
            break
    kept: list[list[Sentence]] = [[] for _ in paragraphs]
    for i, sentence in flat[:cut]:
        if sentence.text.strip() and not _is_furniture(sentence.text, name):
            kept[i].append(sentence)
    return [p for p in kept if p]


def _is_furniture(text: str, name: str) -> bool:
    line = text.strip()
    return bool(
        _SALUTATION.match(line) or _SIGNOFF.match(line) or _is_name_line(line, name)
    )


def known_citations(profile: Profile, excluded: set[str] = frozenset()) -> set[str]:
    """Every id a letter or answer sentence may cite, besides "ad".

    What the writer was shown: the citable catalogue, the stories, the agreed
    explanations and the answer bank, less anything excluded for the kind.
    """
    known = set(build_citable(profile, excluded))
    known |= {s.id for s in profile.stories.stories if s.id not in excluded}
    known |= {
        key
        for key, value in profile.stories.explanations.model_dump(exclude_none=True).items()
        if isinstance(value, str)
    }
    known |= {key.value for key in profile.stories.answers}
    return known


def contract_block(profile: Profile, offer_id: str | None, *, letter: bool) -> str | None:
    """The contract framing for a writer, when the assessment matched an offer."""
    offer = next((o for o in profile.assets.contract_offers if o.id == offer_id), None)
    if offer is None:
        return None
    evidence = ", ".join(offer.evidence) or "(none listed)"
    rule = (
        f"\nThe letter is short: three or four brief paragraphs, under "
        f"{CONTRACT_NOTE_MAX_WORDS} words. Longer is rejected."
        if letter else ""
    )
    try:
        return load_prompt(
            CONTRACT_PROMPT,
            offer=f"{offer.label}: {offer.detail}\nEvidence: {evidence}",
            letter_rule=rule,
        )
    except PromptError as exc:
        raise GenerateError(str(exc)) from exc


def instructions_block(
    *, context: str | None = None, previous: str | None = None,
    note: str | None = None, document: str = "document", contract: str | None = None,
) -> str | None:
    """Alan's context for the application and his revision note, as prompt text.

    Both are things only he knew, given to the tool rather than applied by
    hand afterwards, so they can be counted (REVIEW-2026-10-18, task 2). The
    prompts say what neither can do: license a claim the evidence lacks.
    """
    parts = [contract] if contract else []
    try:
        if context and context.strip():
            parts.append(load_prompt(CONTEXT_PROMPT, context=context.strip()))
        if note and note.strip():
            parts.append(load_prompt(
                REVISION_PROMPT, document=document,
                previous=(previous or "(not available)").strip(), note=note.strip(),
            ))
    except PromptError as exc:
        raise GenerateError(str(exc)) from exc
    return "\n\n".join(parts) or None


def _rewrite_instruction(failures: list[ValidationIssue], *, json_output: bool = False) -> str:
    lines = [
        "## Your previous draft was rejected",
        "",
        "It broke these rules. Fix every one of them and write the piece again.",
        "Do not explain the changes, do not apologise, return only the rewritten",
        "JSON, in the same contract." if json_output else "text.",
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


def build_catalogue(
    profile: Profile, excluded: set[str] = frozenset()
) -> dict[str, str]:
    """Every renderable bullet, keyed by a stable reference.

    ``easy_signs.0``, ``home_design_directory.1``. Entries marked
    ``scorer_only`` are absent: they inform a decision and are never rendered.
    So is anything in ``excluded`` (the role kind's exclusions); the remaining
    bullets keep their indices.
    """
    catalogue: dict[str, str] = {}
    roles = profile.roles
    groups = (roles.roles, roles.founder_track_record, roles.ai_capability)
    for group in groups:
        for entry in group:
            if entry.visibility is Visibility.scorer_only:
                continue
            for index, bullet in enumerate(entry.bullets):
                ref = f"{entry.id}.{index}"
                if not kinds.is_excluded(ref, excluded):
                    catalogue[ref] = bullet.text
    return catalogue


def build_citable(profile: Profile, excluded: set[str] = frozenset()) -> set[str]:
    """Every id a CAREER HIGHLIGHTS bullet may cite as its evidence.

    Wider than `build_catalogue`, and deliberately a different thing. The
    catalogue is what gets *copied verbatim* into EXPERIENCE, so it holds only
    role bullets — putting an earlier-career summary in it would let the model
    reference one from `bullet_refs` and land thirty-year-old text inside a
    dated role block.

    A highlight does not copy; it composes prose and cites the evidence behind
    it. So it may cite anything the selection prompt actually shows it: an
    entry heading or a single bullet within one, in any of the four groups.
    Earlier-career entries appear in that prompt with a bare id and no bullets
    at all, which is why `mlc_nab` — a real, correct citation of Alan's
    superannuation work on a superannuation ad — was reported as unknown.

    Keep this in step with `_render_catalogue`: whatever that shows the model
    is what this has to accept.
    """
    citable = set(build_catalogue(profile, excluded))
    roles = profile.roles
    groups = (roles.roles, roles.founder_track_record, roles.ai_capability)
    for group in groups:
        for entry in group:
            if entry.visibility is Visibility.scorer_only or entry.id in excluded:
                continue
            citable.add(entry.id)
    for entry in roles.earlier_career:
        if entry.visibility is Visibility.scorer_only or entry.id in excluded:
            continue
        citable.add(entry.id)
    return citable


# A bullet whose wording is this close to a line on the page reached the page,
# whichever id it went by.
CONTENT_MATCH = 0.6


def unused_entries(
    selection: "_ResumeSelection",
    profile: Profile,
    excluded: set[str] = frozenset(),
    on_page: list[str] | None = None,
) -> list[UnusedEntry]:
    """Entries offered to the model that reached none of the generated sections.

    Entry granularity, not bullet. "Bullet 4 of easy_signs was not used" is
    noise on every run and would train the reader to skip the list; "datallama
    appears nowhere" is the thing worth seeing, and it was missed twice because
    nothing said it out loud.

    An entry counts as used if it is a selected role, an earlier-career id, or
    the evidence behind a highlight — cited either as the entry itself or as one
    of its bullets.
    """
    used: set[str] = set()
    for role in selection.roles:
        used.add(role.role_id)
        for ref in role.bullet_refs:
            used.add(ref.split(".", 1)[0])
    used.update(selection.earlier_career_ids)
    for highlight in selection.highlights:
        used.add(highlight.source_ref.split(".", 1)[0])

    roles = profile.roles
    groups = (
        ("roles", roles.roles),
        ("founder_track_record", roles.founder_track_record),
        ("ai_capability", roles.ai_capability),
        ("earlier_career", roles.earlier_career),
    )
    unused: list[UnusedEntry] = []
    for group_name, group in groups:
        for entry in group:
            if entry.visibility is Visibility.scorer_only:
                continue
            if entry.id in used or entry.id in excluded:
                continue
            # REVIEW-2026-10-16 D10: the panel listed a certificate printed in
            # EDUCATION, because it matched by id only. Wording on the page counts.
            texts = [b.text for b in getattr(entry, "bullets", [])] or [getattr(entry, "summary", "")]
            if on_page and any(overlap(t, line) >= CONTENT_MATCH for t in texts if t for line in on_page):
                continue
            unused.append(
                UnusedEntry(
                    id=entry.id,
                    group=group_name,
                    label=_entry_label(entry),
                    strong=_is_strong(entry),
                    highlight_only=isinstance(entry, FounderEntry)
                    and _is_ongoing(entry),
                )
            )

    # Most consequential first, so the ordering does not depend on where an
    # entry happens to sit in the YAML. An ongoing venture leads because a
    # highlight is its only route onto the page at all: miss it there and it is
    # absent from the resume entirely, which is how DataLlama went twice.
    order = {name: index for index, (name, _) in enumerate(groups)}
    unused.sort(
        key=lambda e: (not e.highlight_only, not e.strong, order[e.group], e.id)
    )
    return unused


def _entry_label(entry) -> str:
    """A human-readable name, whichever group the entry came from.

    The four groups do not share field names — a role has `title`, a founder
    entry has `role`, an AI capability entry has only `label`.
    """
    label = getattr(entry, "label", None)
    if label:
        return str(label)
    company = getattr(entry, "company", None) or ""
    role = getattr(entry, "title", None) or getattr(entry, "role", None) or ""
    if company and role:
        return f"{company} · {role}"
    return str(company or role or entry.id)


def _is_strong(entry) -> bool:
    """Whether the profile rates this entry's evidence as strong.

    `evidence_strength` sits on each bullet for the three grouped types and on
    the entry itself for earlier-career roles, which have no bullets.
    """
    own = getattr(entry, "evidence_strength", None)
    if own is not None:
        return own is EvidenceStrength.strong
    return any(
        bullet.evidence_strength is EvidenceStrength.strong
        for bullet in getattr(entry, "bullets", [])
    )


def _render_catalogue(
    profile: Profile, catalogue: dict[str, str], excluded: set[str] = frozenset()
) -> str:
    """The catalogue as text for the prompt, grouped so the model can see
    which bullets belong to which role. Excluded entries and bullets are not
    shown at all."""
    lines: list[str] = []
    roles = profile.roles

    lines.append(
        "(A `writer note:` line is a rule about how the entry or bullet above it "
        "may be written about. It is not content: never copy it onto the page. "
        "It binds every highlight, PROFILE sentence and letter sentence that "
        "draws on that material.)\n"
        "(A `story:` tag means the bullet tells that story. Bullets with the "
        "same tag, and the story itself, are one story for every reuse cap; a "
        "bullet with no tag is its own story.)\n"
    )
    lines.append("## Roles (EXPERIENCE section)")
    for role in roles.roles:
        if role.visibility is Visibility.scorer_only or role.id in excluded:
            continue
        lines.append(f"\n{role.id} — {role.title} · {role.company} ({role.sector})")
        _append_writer_note(lines, role.note_for_writer, "  ")
        for index, bullet in enumerate(role.bullets):
            if f"{role.id}.{index}" not in catalogue:
                continue
            lines.append(
                f"  {role.id}.{index}  [{bullet.evidence_strength.value}] "
                f"{bullet.text}{_story_tag(bullet)}"
            )
            _append_writer_note(lines, bullet.note_for_writer, "    ")

    lines.append(
        "\n## Founder track record"
        "\n(Closed ventures go in `earlier_career_ids`, one dated line each — "
        "never in `roles`. An ongoing one has no line: cite its bullets from "
        "the highlights instead.)"
    )
    for entry in roles.founder_track_record:
        if entry.visibility is Visibility.scorer_only or entry.id in excluded:
            continue
        dates = _founder_dates(entry.start, entry.end)
        when = "ongoing" if _is_ongoing(entry) else (dates or "undated")
        lines.append(f"\n{entry.id} [{when}] — {entry.role}, {entry.company}")
        _append_writer_note(lines, entry.note_for_writer, "  ")
        for index, bullet in enumerate(entry.bullets):
            if f"{entry.id}.{index}" not in catalogue:
                continue
            lines.append(f"  {entry.id}.{index}  {bullet.text}{_story_tag(bullet)}")
            _append_writer_note(lines, bullet.note_for_writer, "    ")

    lines.append(
        "\n## AI capability"
        "\n(Evidence for the highlights and the PROFILE paragraphs only. These "
        "are not employment and have no body section.)"
    )
    for entry in roles.ai_capability:
        if entry.visibility is Visibility.scorer_only or entry.id in excluded:
            continue
        lines.append(f"\n{entry.id} — {entry.label}")
        _append_writer_note(lines, entry.note_for_writer, "  ")
        for index, bullet in enumerate(entry.bullets):
            if f"{entry.id}.{index}" not in catalogue:
                continue
            lines.append(f"  {entry.id}.{index}  {bullet.text}{_story_tag(bullet)}")
            _append_writer_note(lines, bullet.note_for_writer, "    ")

    lines.append(
        "\n## Earlier career (undated, one condensed line each)"
        "\n(Cite one of these from a highlight by its bare id — they have no "
        "bullets. Thirty years of domain evidence lives here.)"
    )
    for entry in roles.earlier_career:
        if entry.visibility is Visibility.scorer_only or entry.id in excluded:
            continue
        lines.append(f"  {entry.id} — {entry.company}: {entry.summary}")

    return "\n".join(lines)


def _story_tag(bullet) -> str:
    """Which story a bullet tells, so the writer can see what the reuse caps count.

    Half of the drafts rejected in October were rejected for telling one story
    twice, and the writer could not have known: the link between a bullet and
    its story lived only in the profile, never in what it was shown.
    """
    return f"  (story: {bullet.linked_story})" if bullet.linked_story else ""


def _append_writer_note(lines: list[str], note: str | None, indent: str) -> None:
    if note:
        lines.append(f"{indent}writer note: {' '.join(note.split())}")


def _render_stories(profile: Profile, excluded: set[str] = frozenset()) -> str:
    lines = []
    for story in profile.stories.stories:
        if story.id in excluded:
            continue
        lines.append(
            f"{story.id} — {story.label}\n"
            f"  situation: {story.situation}\n"
            f"  action: {story.action}\n"
            f"  result: {story.result}"
        )
        lines += _mechanism_lines(story, "  ")
        _append_writer_note(lines, story.note_for_writer, "  ")
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


def _mechanism_lines(story, indent: str) -> list[str]:
    """A story's order, mechanism and causes, and what is false about it."""
    lines = []
    if story.sequence:
        # Not numbered: a numbered step was cited as `story_id.0`, as though
        # it were a bullet. Cite the story itself.
        lines.append(f"{indent}sequence, in this order (cite the story id, not a step):")
        lines += [f"{indent}  - {step}" for step in story.sequence]
    if story.how_it_worked:
        lines.append(f"{indent}how it worked: {story.how_it_worked}")
    if story.why_this_way:
        lines.append(f"{indent}why this way: {story.why_this_way}")
    if story.cause_effect:
        lines.append(f"{indent}causes Alan states (the only ones a sentence may claim):")
        lines += [f"{indent}  - {claim}" for claim in story.cause_effect]
    if story.not_true:
        lines.append(f"{indent}NOT TRUE — never state or imply any of these:")
        lines += [f"{indent}  - {claim}" for claim in story.not_true]
    return lines


def _founder_line(entry: FounderEntry) -> tuple[str, ValidationIssue | None]:
    """One EARLIER CAREER line for a closed venture, in the master's format.

    From `AlanBronResumeMaster102026.docx`, which wins over any spec that
    disagrees with it:

        Co-founder & CTO, Australian Home Design Directory (2006–16) — sole
        architect; built the entire platform, grew to 1M+ annual visitors,
        acquired after a competitive bidding process.

    An *ongoing* venture is deliberately not renderable here. The master lists
    DataLlama once, as a CAREER HIGHLIGHT, and nowhere else — and its
    `note_for_scorer` says never to present it as full-time work or use it to
    fill a gap in the employment timeline. A dated line among closed ventures
    does neither job well. Its bullets still reach the page through highlights.
    """
    if _is_ongoing(entry):
        return "", ValidationIssue(
            rule="ongoing venture in earlier career",
            severity=Severity.blocker,
            detail=(
                f"{entry.id!r} is still running ({entry.start}–present) and does "
                "not belong in EARLIER CAREER, which lists closed ventures. Cite "
                "its bullets from CAREER HIGHLIGHTS instead — that is where the "
                "master resume puts it."
            ),
            excerpt=entry.id,
        )
    if not entry.summary:
        return "", ValidationIssue(
            rule="missing summary",
            severity=Severity.blocker,
            detail=(
                f"{entry.id!r} has no `summary` in the profile, and the model "
                "may not write one — resume prose is copied, never composed. "
                "Add a summary line to this entry in roles.yaml."
            ),
            excerpt=entry.id,
        )
    dates = _founder_dates(entry.start, entry.end)
    heading = f"{entry.role}, {entry.company}"
    if dates:
        heading += f" ({dates})"
    return f"{heading} — {entry.summary}", None


def _is_ongoing(entry: FounderEntry) -> bool:
    return entry.end is not None and entry.end.lower() == PRESENT


def _founder_dates(start: str | None, end: str | None) -> str:
    """``2006–16`` — the master's parenthetical style for a closed venture.

    Two-digit end year, en dash, no spaces. Distinct from `format_dates`,
    which renders the tab-stopped range beside a role heading. Same age-signal
    policy either way: the years are shown, the span is never computed.
    """
    if start is None:
        return ""
    start_year = start.split("-")[0]
    if end is None:
        return start_year
    end_year = end.split("-")[0]
    if end_year == start_year:
        return start_year
    return f"{start_year}\u2013{end_year[-2:]}"


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


def _check_citation(ref: str, citable: set[str]) -> list[ValidationIssue]:
    """A highlight's `source_ref`, which may name an entry or a single bullet."""
    if ref in citable:
        return []
    return [
        ValidationIssue(
            rule="unknown reference",
            severity=Severity.blocker,
            detail=(
                f"A CAREER HIGHLIGHTS bullet cites {ref!r}, which is not an id "
                "anywhere in the profile. Every id the selection prompt offers "
                "is citable — a role, a founder venture, an AI capability "
                "entry, an earlier-career line, or one bullet within any of "
                "them — so an id that fails here was invented. Check the "
                "sentence it supports before keeping it."
            ),
            excerpt=ref,
        )
    ]


def _unknown(ref: str, kind: str) -> ValidationIssue:
    return ValidationIssue(
        rule="unknown reference",
        severity=Severity.blocker,
        detail=(
            f"The model referenced a {kind} {ref!r} that is not in the "
            f"profile's {kind} list. Check whether the id exists in another "
            "section before assuming it was invented — a real id in the wrong "
            "slot looks identical to a fabricated one here."
        ),
        excerpt=ref,
    )


# --------------------------------------------------------------------------- #
# Role kind (spec 003)
# --------------------------------------------------------------------------- #

_KIND_WORDS = {
    "people_focused": "people-focused",
    "delivery_focused": "delivery-focused",
    "technical_lead": "technical lead",
    "ai_enablement": "AI enablement",
}


def kind_label(kind) -> str:
    return _KIND_WORDS.get(getattr(kind, "value", kind), str(kind))


def role_kind_block(kind: RoleClassification | None) -> str:
    """The `{role_kind}` placeholder: what kind of role this is, and why."""
    if kind is None:
        return "Not classified. Weight evidence by the assessment alone."
    text = f"Primary: {kind_label(kind.primary)}"
    if kind.secondary:
        text += f"; secondary: {kind_label(kind.secondary)}"
    return f"{text}. {kind.reason}"


def _lead_issues(
    selection: _ResumeSelection,
    profile: Profile,
    kind: RoleClassification | None,
    assessment: FitAssessment | None = None,
) -> list[ValidationIssue]:
    """The first highlight is what a reader meets first; both of these block.

    REVIEW-2026-10-16 D6. When the assessment names what to lead with and the
    first item is evidence in the profile, the first highlight must cite it:
    the scorer read the ad against the whole profile, and the writer led JD 85
    on five things it never mentioned. Otherwise the highlight must be of the
    ad's kind. The assessment wins where the two disagree, because it is about
    this ad and the kind is about ads like it.
    """
    if not selection.highlights:
        return []
    ref = selection.highlights[0].source_ref
    lead = lead_ref(assessment, profile) if assessment else None
    if lead is not None:
        if _answers_ref(lead, ref, profile):
            return []
        return [
            ValidationIssue(
                rule="lead not as assessed",
                severity=Severity.blocker,
                detail=(
                    f"The assessment says to lead with {lead!r}; the first CAREER "
                    f"HIGHLIGHT cites {ref!r}. Open on {lead!r}: that id, its entry, "
                    "a bullet within it, or a bullet that tells that story."
                ),
                excerpt=ref,
            )
        ]
    if kind is None or kinds.lead_is_on_kind(ref, profile, kind.primary):
        return []
    return [
        ValidationIssue(
            rule="lead not on-kind",
            severity=Severity.blocker,
            detail=(
                f"This is a {kind_label(kind.primary)} ad, and the first CAREER "
                f"HIGHLIGHT cites {ref!r}, which is not tagged as that kind of "
                "evidence. Open on evidence of the kind the ad hires for."
            ),
            excerpt=ref,
        )
    ]


_ID_TOKEN = re.compile(r"[a-z0-9_]+(?:\.\d+)?")


def lead_ref(assessment: FitAssessment, profile: Profile) -> str | None:
    """The profile id the assessment's first `emphasise` item names, if any."""
    if not assessment.emphasise:
        return None
    known = build_citable(profile) | {s.id for s in profile.stories.stories}
    for token in _ID_TOKEN.findall(assessment.emphasise[0].lower()):
        if token in known:
            return token
    return None


def _answers_ref(wanted: str, cited: str, profile: Profile) -> bool:
    if cited == wanted or cited.split(".", 1)[0] == wanted or wanted.split(".", 1)[0] == cited:
        return True
    return story_of(cited, profile) == wanted


def _excluded(ref: str, kind: RoleClassification | None) -> ValidationIssue:
    label = kind_label(kind.primary) if kind else "this kind of"
    return ValidationIssue(
        rule="excluded evidence",
        severity=Severity.blocker,
        detail=(
            f"{ref!r} is excluded from written documents for {label} roles in "
            "the profile, and was not shown to the model, yet it was cited. "
            "It has been left off the page."
        ),
        excerpt=ref,
    )


def _must_cover_block(assessment: FitAssessment, excluded: set[str]) -> str:
    rows = cover.must_cover(assessment, excluded)
    if not rows:
        return "(none listed)"
    return "\n".join(f"- {requirement}  ->  cite {ref}" for requirement, ref in rows)


def evidence_text(profile: Profile, ref: str) -> str | None:
    """The full text behind a cited id, for the claim check. None if unknown.

    A bullet's text; an entry's heading and every bullet; a story's situation,
    action and result; an explanation or answer-bank entry. Never a scorer
    note: those are facts the writer is kept from, and the checker reads what
    the writer was allowed to rely on.
    """
    entry_id, _, index = ref.partition(".")
    r = profile.roles
    for group in (r.roles, r.founder_track_record, r.ai_capability):
        for entry in group:
            if entry.id != entry_id:
                continue
            if index.isdigit() and int(index) < len(entry.bullets):
                # With the entry's heading: a bullet alone does not say whose
                # it is. "Founder, architect" for a bullet of a Co-founder &
                # CTO entry was marked unsupported because the checker saw
                # only "built the initial versions alone as architect".
                return f"{_entry_label(entry)}: {entry.bullets[int(index)].text}"
            if not index:
                return f"{_entry_label(entry)}: " + " ".join(b.text for b in entry.bullets)
    for entry in r.earlier_career:
        if entry.id == ref:
            return f"{entry.company}: {entry.summary}"
    for story in profile.stories.stories:
        if story.id == ref:
            text = (
                f"{story.label}. Situation: {story.situation} Action: {story.action} "
                f"Result: {story.result}"
            )
            mechanism = _mechanism_lines(story, "")
            return f"{text}\n" + "\n".join(mechanism) if mechanism else text
    explanations = profile.stories.explanations.model_dump(exclude_none=True)
    if isinstance(explanations.get(ref), str):
        return explanations[ref]
    for key, text in profile.stories.answers.items():
        if key.value == ref:
            return text
    return None


def resume_text(content: ResumeContent) -> str:
    """The resume as plain text, in the rendered order, for the reviewer."""
    lines = [content.name, content.tagline, "", "PROFILE", *content.profile_paragraphs, ""]
    lines.append("CAREER HIGHLIGHTS")
    lines += [f"- {label} — {text}" for label, text in content.highlights]
    lines += ["", "CORE SKILLS"]
    lines += [f"- {category.label}: {category.skills}" for category in content.skills]
    lines += ["", "EXPERIENCE"]
    for role in content.roles:
        lines.append(f"{role.title} · {role.company}  {role.dates}")
        lines += [f"- {bullet}" for bullet in role.bullets]
    if content.earlier_career:
        lines += ["", "EARLIER CAREER", *(f"- {line}" for line in content.earlier_career)]
    if content.education:
        lines += ["", "EDUCATION & CERTIFICATIONS", *content.education]
    return "\n".join(lines)


def _resume_places(selection: _ResumeSelection) -> list[tuple[str, list[str]]]:
    places = [
        (f"PROFILE paragraph {n}", refs) for n, refs in enumerate(selection.profile_refs, 1)
    ]
    places += [
        (f"highlight {n}", [h.source_ref]) for n, h in enumerate(selection.highlights, 1)
    ]
    places += [
        (f"bullet {ref}", [ref]) for role in selection.roles for ref in role.bullet_refs
    ]
    return places


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[“”‘’\"']", "", text).casefold().split())


def check_company_sentences(
    paragraphs: list[list[Sentence]], ad_text: str
) -> list[ValidationIssue]:
    """The one sentence about the employer quotes the ad, and there is one at most.

    A letter with nothing about the company reads as generic; one that says
    something the ad does not is worse. So the model must hand over the ad's
    own words as `quote`, and the quote must be in the ad.
    """
    quoted = [s for p in paragraphs for s in p if s.quote]
    issues = []
    haystack = _normalise(ad_text)
    for sentence in quoted:
        if _normalise(sentence.quote) not in haystack:
            issues.append(
                ValidationIssue(
                    rule="company claim not in ad",
                    severity=Severity.blocker,
                    detail=(
                        "A sentence about the employer quotes words that are not "
                        "in the ad. Say only what the ad says about them."
                    ),
                    excerpt=sentence.text,
                )
            )
    if len(quoted) > 1:
        issues.append(
            ValidationIssue(
                rule="company sentences",
                severity=Severity.warning,
                detail=f"The letter has {len(quoted)} sentences about the employer; one is enough.",
                excerpt=quoted[1].text,
            )
        )
    return issues


_WORD = re.compile(r"[a-z0-9+#.]+")


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


def overlap(a: str, b: str) -> float:
    """Share of the smaller text's words found in the other, 0..1."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def must_have_gaps(jd: JobDescription, assessment: FitAssessment) -> list[str]:
    """Requirements marked `gap` that are one of the ad's must-haves.

    The assessment's requirements mix must-haves with nice-to-haves, and a
    letter once volunteered a Kubernetes gap the ad listed only as an "e.g.".
    A requirement counts as a must-have when it shares most of its words with
    one of `jd.must_haves` and is not a nice-to-have.
    """
    out = []
    for row in assessment.requirements:
        if row.status.value != "gap":
            continue
        if any(overlap(row.requirement, nice) >= 0.6 for nice in jd.nice_to_haves):
            continue
        if any(overlap(row.requirement, _firm_part(must)) >= 0.5 for must in jd.must_haves):
            out.append(row.requirement)
    return out


# Words after which a must-have turns into examples or wishes. "Container
# orchestration (e.g. Kubernetes)" asks for orchestration, not for Kubernetes.
_SOFTENER = re.compile(
    r"\(?\b(?:e\.g\.?|eg|such as|for example|ideally|preferably|a plus|nice to have|bonus)\b",
    re.IGNORECASE,
)


def _firm_part(must_have: str) -> str:
    return _SOFTENER.split(must_have, maxsplit=1)[0]


def _repeats_resume(paragraphs, on_resume: dict[str, str]) -> list[ValidationIssue]:
    """A letter sentence that copies a line the resume already carries.

    The letter is written after the resume and is told what is on it; this is
    the check that it listened. A story may come back in the letter once, but
    told differently — a reader of both documents should not meet the same
    sentence twice.
    """
    issues = []
    for paragraph in paragraphs:
        for sentence in paragraph:
            for ref, text in on_resume.items():
                if overlap(sentence.text, text) >= REPEAT_OVERLAP:
                    issues.append(
                        ValidationIssue(
                            rule="letter repeats the resume",
                            severity=Severity.blocker,
                            detail=(
                                f"A letter sentence restates the resume's {ref}. Tell "
                                "it differently or use evidence the resume does not show."
                            ),
                            excerpt=sentence.text[:120],
                        )
                    )
                    break
    return issues


def _page_lines(content: ResumeContent) -> list[str]:
    """Every line of prose the resume prints, for matching evidence by wording."""
    lines = [*content.profile_paragraphs, *(text for _, text in content.highlights)]
    lines += [b for role in content.roles for b in role.bullets]
    lines += [*content.earlier_career, *content.education]
    return lines
