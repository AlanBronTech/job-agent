"""The work a UI run does: a service call, and a JSON-able summary of what it did.

The summary is what the run page shows afterwards, so it keeps exactly what
the CLI prints after the same command: files written, every validation issue,
and the profile entries used nowhere. Nothing is decided here.
"""

from __future__ import annotations

from datetime import date, datetime

from jobagent.adapters.llm import RunContext
from jobagent.services import documents
from jobagent.services.documents import GenerationFailed
from jobagent.services.workspace import Workspace
from jobagent.web.runner import RunFailed

_STAGE = {
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
            "superseded": result.superseded.name if result.superseded else None,
            "warnings": result.warnings,
        }

    return work
