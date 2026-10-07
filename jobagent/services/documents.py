"""Generate application documents: every guard `generate` had, for both front ends.

Moved out of `cli/generate.py` so the UI cannot become the way around them.
Every refusal is raised before the model client is built, so none costs
anything; the order is the CLI's order, including recording an overrule before
the overwrite check, because the overrule is a fact about Alan's judgement
whether or not this particular run goes ahead.

The folder is written through `ws.documents`. `docx_writer` still takes a
path, which the store hands it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from jobagent.adapters import docs
from jobagent.adapters.docx_writer import (
    CoverLetterContent,
    DocxError,
    write_cover_letter,
    write_resume,
)
from jobagent.adapters.llm import CallType, LLMError, RunContext, get_client
from jobagent.core import history, store
from jobagent.core import roles as kinds
from jobagent.core.generate import (
    GenerateError,
    build_answers,
    build_cover_letter,
    build_resume,
    resume_text,
)
from jobagent.core.validation import banned_phrases
from jobagent.core.models import Application, JobDescription, Verdict
from jobagent.core.profile import ProfileError, load_profile
from jobagent.core.store import StoreError
from jobagent.services.refusals import (
    AlreadyGenerated,
    NoModel,
    NoSuchAd,
    NothingSelected,
    NotScored,
    ProfileInvalid,
    ProfileMissing,
    SupersedeFailed,
    VerdictIsSkip,
)
from jobagent.services import checks, reapply, role_kind
from jobagent.services.results import GeneratePlan, GenerateResult
from jobagent.services.scoring import refuse_if_reapplying
from jobagent.services.workspace import Workspace


class GenerationFailed(Exception):
    """A model call or a write failed after spending began.

    Not a refusal: money may already be gone. `written` lists what did land on
    disk before the failure, so it can be shown as incomplete rather than read
    as a finished set.
    """

    def __init__(self, stage: str, cause: Exception, written: list[Path]) -> None:
        super().__init__(str(cause))
        self.stage = stage  # "classify" | "resume" | "cover" | "answers" | "write"
        self.cause = cause
        self.written = written


@dataclass
class _Loaded:
    jd: JobDescription
    assessment: object
    history: object
    warnings: list[str] = field(default_factory=list)


def planned_names(
    jd: JobDescription,
    when: date,
    *,
    resume: bool,
    cover: bool,
    answers: bool,
    review: bool = False,
) -> list[str]:
    """Exactly the file names a run would write, in the order it writes them.

    `assessment.md` and `job-ad.md` are unconditional: every run rewrites the
    record of why the documents were cut the way they were.
    """
    names: list[str] = []
    if resume:
        names.append(docs.document_name("Resume", jd, when=when))
    if cover:
        names.append(docs.document_name("CoverLetter", jd, when=when))
    if answers:
        names.append("answers.md")
    if review:
        names.append("review.md")
    return names + ["assessment.md", "job-ad.md"]


def plan(
    ws: Workspace, jd_id: int, *, resume: bool, cover: bool, answers: bool, when: date
) -> GeneratePlan:
    """What a run would do. Spends nothing; the UI shows it before asking to confirm."""
    if not (resume or cover or answers):
        raise NothingSelected()
    loaded = _load(ws, jd_id)
    names = planned_names(loaded.jd, when, resume=resume, cover=cover, answers=answers)
    return GeneratePlan(
        jd=loaded.jd,
        verdict=loaded.assessment.verdict,
        rationale=loaded.assessment.rationale,
        needs_overrule=loaded.assessment.verdict is Verdict.skip,
        folder=Path(ws.documents.folder_name(loaded.jd, when)),
        names=names,
        clashes=_clashes(ws, loaded.jd, when, names),
        history=loaded.history,
        reapply=reapply.check(ws, jd_id, when),
        role_kind=role_kind.stored(ws, jd_id),
    )


def generate(
    ws: Workspace,
    config,
    ctx: RunContext,
    jd_id: int,
    *,
    resume: bool,
    cover: bool,
    questions: list[str],
    overrule: bool = False,
    supersede: bool = False,
    overwrite: bool = False,
    today: date,
    now: datetime,
    contact: str | None = None,
    before_spend=None,
    check_claims: bool | None = None,
    review: bool | None = None,
) -> GenerateResult:
    """Run generate. `before_spend` is called once every refusal has passed and
    immediately before the first model call: the CLI prints its cost line there."""
    if supersede and overwrite:
        raise ValueError("supersede and overwrite are mutually exclusive")
    # None means "as configured"; both checks are on unless switched off.
    check_claims = config.check_claims if check_claims is None else check_claims
    review = config.review if review is None else review
    if not (resume or cover or questions):
        raise NothingSelected()

    loaded = _load(ws, jd_id)
    jd, assessment = loaded.jd, loaded.assessment
    refuse_if_reapplying(ws, jd_id, today)
    warnings: list[str] = []

    if assessment.verdict is Verdict.skip:
        if not overrule:
            raise VerdictIsSkip(assessment.rationale)
        warning = record_overrule(ws, jd_id)
        if warning:
            warnings.append(warning)

    names = planned_names(
        jd, today, resume=resume, cover=cover, answers=bool(questions), review=review
    )
    # With supersede the clash is expected: the folder is moved aside below.
    if not overwrite and not supersede:
        clashes = _clashes(ws, jd, today, names)
        if clashes:
            raise AlreadyGenerated(ws.documents.folder_name(jd, today), clashes)

    if ws.profile_dir is None:
        raise ProfileMissing()
    try:
        profile = load_profile(ws.profile_dir)
    except ProfileError as exc:
        raise ProfileInvalid(str(exc)) from exc

    try:
        client = get_client(CallType.generate, config, ctx)
        kind = role_kind.stored(ws, jd_id)
        classify_client = None if kind else get_client(CallType.classify, config, ctx)
        review_client = (
            get_client(CallType.review, config, ctx) if (check_claims or review) else None
        )
    except LLMError as exc:
        raise NoModel(str(exc)) from exc

    # Last, after every refusal, so a run that was going to be refused anyway
    # does not leave the folder renamed; first, before any model call, so a
    # failed move costs nothing.
    superseded: Path | None = None
    if supersede:
        try:
            moved = ws.documents.supersede(jd, today, now)
        except docs.DocsError as exc:
            raise SupersedeFailed(ws.documents.folder_name(jd, today), str(exc)) from exc
        superseded = Path(moved) if moved else None

    # -- spending starts here ------------------------------------------------
    if before_spend is not None:
        before_spend()
    written: list[Path] = []
    issues = []
    unused = []
    coverage = []
    claims = None  # None: not run (switched off, or nothing to check)
    rendered: dict[str, str] = {}  # what the reviewer reads

    if kind is None:
        try:
            kind = role_kind.ensure(
                ws, config, ctx, jd_id, client_factory=lambda: classify_client
            )
        except role_kind.RoleKindFailed as exc:
            raise GenerationFailed("classify", exc, written) from exc

    if resume:
        try:
            built = build_resume(
                jd, profile, assessment, client=client, today=today, kind=kind
            )
        except GenerateError as exc:
            raise GenerationFailed("resume", exc, written) from exc
        issues += built.issues
        unused = built.unused
        coverage = getattr(built, "coverage", [])
        rendered["resume"] = (
            built.content if isinstance(built.content, str) else resume_text(built.content)
        )
        path = ws.documents.path_for_write(jd, today, docs.document_name("Resume", jd, when=today))
        written.append(_write(lambda: write_resume(built.content, path), written))

    if cover:
        try:
            letter = build_cover_letter(jd, profile, assessment, client=client, kind=kind)
        except GenerateError as exc:
            raise GenerationFailed("cover", exc, written) from exc
        issues += letter.issues
        rendered["cover letter"] = letter.text
        sentences = getattr(letter, "sentences", [])
        if check_claims and sentences:
            claims = checks.check_claims(
                config, ctx, sentences, profile, client_factory=lambda: review_client
            )
            issues += claim_issues(claims)
        content = CoverLetterContent(
            name=profile.roles.person.name,
            contact=contact if contact is not None else contact_line(profile),
            date=f"{today:%-d %B %Y}",
            recipient=[jd.company] if jd.company else [],
            paragraphs=[p.strip() for p in letter.text.split("\n\n") if p.strip()],
        )
        path = ws.documents.path_for_write(jd, today, docs.document_name("CoverLetter", jd, when=today))
        written.append(_write(lambda: write_cover_letter(content, path), written))

    if questions:
        try:
            built_answers = build_answers(
                questions, jd, profile, assessment, client=client, kind=kind
            )
        except GenerateError as exc:
            raise GenerationFailed("answers", exc, written) from exc
        issues += built_answers.issues
        rendered["answers"] = built_answers.text
        written.append(
            _write(lambda: ws.documents.write_text(jd, today, "answers.md", built_answers.text), written)
        )

    reviewed = None
    if review:
        excluded = kinds.excluded_ids(profile, kinds.kinds_of(kind))
        reviewed = checks.review(
            config,
            ctx,
            jd,
            rendered,
            kind=kind,
            excluded=checks.excluded_descriptions(profile, excluded),
            banned=banned_phrases(profile.voice),
            client_factory=lambda: review_client,
        )
        written.append(
            _write(
                lambda: ws.documents.write_text(
                    jd, today, "review.md", checks.review_markdown(reviewed)
                ),
                written,
            )
        )

    written.append(
        _write(
            lambda: ws.documents.write_text(
                jd,
                today,
                "assessment.md",
                docs.assessment_markdown(
                    assessment, jd, issues, role_kind=kind, coverage=coverage
                ),
            ),
            written,
        )
    )
    written.append(
        _write(lambda: ws.documents.write_text(jd, today, "job-ad.md", docs.job_ad_markdown(jd)), written)
    )

    return GenerateResult(
        folder=written[0].parent,
        written=written,
        issues=issues,
        unused=unused,
        superseded=superseded,
        warnings=warnings,
        role_kind=kind,
        coverage=coverage,
        claims=claims,
        review=reviewed,
        ready=is_ready(issues, claims, reviewed),
    )


def is_ready(issues, claims, reviewed) -> bool:
    """Ready only when nothing blocks and the review ran and found nothing.

    A review that failed or was switched off is "not reviewed", never ready;
    so is a claim check that did not complete.
    """
    if any(issue.severity.value == "blocker" for issue in issues):
        return False
    if isinstance(claims, checks.NotChecked):
        return False
    return isinstance(reviewed, checks.Review) and not reviewed.blocking


def claim_issues(claims) -> list:
    """Mismatches from the claim check as blockers, beside the code checks'."""
    from jobagent.core.validation import Severity, ValidationIssue

    if not isinstance(claims, list):
        return []
    return [
        ValidationIssue(
            rule="claim mismatch",
            severity=Severity.blocker,
            detail=m.problem,
            excerpt=m.sentence,
        )
        for m in claims
    ]


def record_overrule(ws: Workspace, jd_id: int) -> str | None:
    """Note that Alan generated documents against a `skip`.

    Recorded rather than merely permitted, because the interesting question is
    not whether he can overrule the scorer — he obviously can — but who turns
    out to be right, and that is only answerable if the disagreements are
    counted. Returns a warning instead of raising: bookkeeping never stops the
    documents being written.
    """
    try:
        with store.open_store(ws.db_path) as conn:
            application = store.get_application(conn, jd_id) or Application(
                jd_id=jd_id, updated_at=datetime.now(timezone.utc)
            )
            application.overrode_scorer = True
            application.updated_at = datetime.now(timezone.utc)
            store.save_application(conn, application)
    except StoreError as exc:
        return f"Could not record the override: {exc}"
    return None


def contact_line(profile) -> str:
    person = profile.roles.person
    parts = [person.location, person.phone, person.email]
    return "   ·   ".join(part for part in parts if part)


# --------------------------------------------------------------------------- #


def _load(ws: Workspace, jd_id: int) -> _Loaded:
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
        if jd is None:
            raise NoSuchAd(jd_id)
        assessment = store.latest_assessment(conn, jd_id)
        seen_before = history.company_history(conn, jd)
    if assessment is None:
        raise NotScored(jd_id)
    return _Loaded(jd=jd, assessment=assessment, history=seen_before)


def _clashes(ws: Workspace, jd: JobDescription, when: date, names: list[str]):
    """The planned files already on disk in this month's folder, with their times.

    Only the names this run would write. A folder can hold `interview-prep.md`
    from a `prep` run that generate would not touch, and reporting that as at
    risk would be a false alarm — the one thing a guard like this cannot
    afford, because a guard that cries wolf gets passed `--overwrite`
    reflexively and stops being a guard.
    """
    current = ws.documents.list_for(jd, when).current
    if current is None:
        return []
    wanted = set(names)
    return [(f.name, f.modified) for f in current.files if f.name in wanted]


def _write(action, written: list[Path]) -> Path:
    try:
        return action()
    except (DocxError, docs.DocsError) as exc:
        raise GenerationFailed("write", exc, written) from exc
