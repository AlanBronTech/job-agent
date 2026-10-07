"""The work a UI run does: a service call, and a JSON-able summary of what it did.

The summary is what the run page shows afterwards, so it keeps exactly what
the CLI prints after the same command: files written, every validation issue,
and the profile entries used nowhere. Nothing is decided here.
"""

from __future__ import annotations

from datetime import date, datetime

from jobagent.adapters.llm import RunContext
from jobagent.core.jd import JDError
from jobagent.core.scoring import ScoringError
from jobagent.core.store import StoreError
from jobagent.services import ads, batches, documents, scoring
from jobagent.services.documents import GenerationFailed
from jobagent.services.workspace import Workspace
from jobagent.web.runner import RunFailed

_STAGE = {
    "classify": "Could not classify the role",
    "resume": "Could not build the resume",
    "cover": "Could not write the cover letter",
    "answers": "Could not answer the questions",
    "write": "Could not write the documents",
}


def generate(
    ws: Workspace,
    config,
    ctx: RunContext,
    jd_id: int,
    *,
    resume: bool,
    cover: bool,
    questions: list[str],
    overrule: bool,
    supersede: bool,
    today: date,
):
    def work() -> dict:
        try:
            result = documents.generate(
                ws, config, ctx, jd_id,
                resume=resume, cover=cover, questions=questions,
                overrule=overrule, supersede=supersede,
                today=today, now=datetime.now(),
            )
        except GenerationFailed as failure:
            message = f"{_STAGE[failure.stage]}: {failure.cause}"
            if failure.written:
                message += (
                    ". Written before it failed, so incomplete: "
                    + ", ".join(p.name for p in failure.written)
                )
            raise RunFailed(message) from failure
        return {
            "jd_id": jd_id,
            "folder": result.folder.name,
            "written": [p.name for p in result.written],
            "issues": [
                {"rule": i.rule, "severity": i.severity.value, "detail": i.detail, "excerpt": i.excerpt}
                for i in result.issues
            ],
            "blocked": any(i.severity.value == "blocker" for i in result.issues),
            "unused": [
                {"id": u.id, "label": u.label, "strong": u.strong, "highlight_only": u.highlight_only}
                for u in result.unused
            ],
            "coverage": [
                {"requirement": c.requirement, "status": c.status, "where": c.where}
                for c in result.coverage
            ],
            "superseded": result.superseded.name if result.superseded else None,
            "warnings": result.warnings,
        }

    return work


def add_ad(ws: Workspace, config, ctx: RunContext, ad, *, source: str | None):
    def work() -> dict:
        try:
            result = ads.add(ws, config, ctx, ad, source=source)
        except JDError as exc:
            raise RunFailed(f"Could not parse the job description: {exc}") from exc
        except StoreError as exc:
            raise RunFailed(f"Parsed, but could not save: {exc}") from exc
        return {
            "jd_id": result.jd.id,
            "title": result.jd.title,
            "company": result.jd.company,
            "thin_chars": result.thin_chars,
        }

    return work


def score(ws: Workspace, config, ctx: RunContext, jd_id: int, *, force: bool):
    def work() -> dict:
        try:
            result = scoring.score(ws, config, ctx, jd_id, force=force)
        except ScoringError as exc:
            raise RunFailed(f"Could not score this job description: {exc}") from exc
        a = result.assessment
        return {
            "jd_id": jd_id,
            "verdict": a.verdict.value,
            "overall_score": a.overall_score,
            "recruiter_screen_score": a.recruiter_screen_score,
            "warnings": result.warnings,
        }

    return work


def parse_batch(ws: Workspace, config, batch_id: int):
    def work() -> dict:
        batches.parse(ws, config, batch_id, source="ui")
        return {"batch_id": batch_id}

    return work
