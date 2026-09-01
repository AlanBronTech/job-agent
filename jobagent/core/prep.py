"""Interview preparation for one job, from the ad, the profile and the score.

The hard questions are not predicted. They are carried across from the fit
assessment's ``challenge_points`` — the objections the scorer already found in
the gap between this ad and the profile — because those are the questions that
have actually been asked. The Toshiba assessment named the Kubernetes and
GitLab gap, and that is exactly what came up in the real Toshiba process.

Everything else the model supplies: what else they are likely to ask, and
which story from the bank answers it. Story references are validated, in the
same way resume bullets are: an id the model invents fails a lookup rather
than sending Alan into an interview to tell a story that does not exist.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import ValidationError

from jobagent.adapters.llm import LLMClient, LLMError
from jobagent.core.models import (
    FitAssessment,
    InterviewPrep,
    JobDescription,
    PrepQuestion,
    Profile,
)
from jobagent.core.prompts import PromptError, load_prompt
from jobagent.core.validation import ValidationIssue, validate_rendered

PROMPT_NAME = "interview_prep"
# Eight to twelve questions, each with an answer sketch and a story
# reference, plus the questions to ask them. A dense ad (Ebury, JD 22)
# ran the answer off the end of an 8,192-token ceiling, and a truncated
# answer is a hard failure, not a degraded one — this matches scoring.
MAX_TOKENS = 16384


class PrepError(Exception):
    """Interview preparation could not be produced."""


def prepare(
    jd: JobDescription,
    profile: Profile,
    assessment: FitAssessment,
    *,
    client: LLMClient,
    interviewers: list[str] | None = None,
    prepared_at: datetime | None = None,
) -> tuple[InterviewPrep, list[ValidationIssue]]:
    """Produce interview prep. Returns the prep and any validation issues."""
    interviewers = interviewers or []
    stories = {story.id: story for story in profile.stories.stories}

    try:
        prompt = load_prompt(
            PROMPT_NAME,
            jd_json=_summary(jd),
            assessment_json=_assessment(assessment),
            stories=_render_stories(profile),
            interviewers="\n".join(f"- {name}" for name in interviewers) or "Not known.",
            voice=profile.voice,
        )
    except PromptError as exc:
        raise PrepError(str(exc)) from exc

    try:
        parsed, _ = client.complete_json(
            prompt=prompt, label=PROMPT_NAME, max_tokens=MAX_TOKENS
        )
    except LLMError as exc:
        raise PrepError(f"Model call failed while preparing: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PrepError(
            f"Expected a JSON object from the model, got {type(parsed).__name__}."
        )

    issues: list[ValidationIssue] = []
    questions: list[PrepQuestion] = []

    # The assessment's challenge points come first and are marked hard. They
    # are not the model's guesses — they are what the scorer already found.
    for challenge in assessment.challenge_points:
        questions.append(
            PrepQuestion(
                question=challenge.point,
                why_asked=(
                    "Raised by the fit assessment as a gap between this ad and "
                    "the profile."
                ),
                answer_outline=challenge.response,
                hard=True,
            )
        )

    for entry in parsed.get("questions", []):
        try:
            question = PrepQuestion.model_validate(entry)
        except ValidationError as exc:
            raise PrepError(f"A question did not match the contract.\n{exc}") from exc
        if question.story_ref and question.story_ref not in stories:
            issues.append(
                ValidationIssue(
                    rule="unknown reference",
                    severity=_blocker(),
                    detail=(
                        f"Story {question.story_ref!r} is not in the story bank. "
                        "Answering from a story that does not exist is worse "
                        "than answering without one."
                    ),
                    excerpt=question.story_ref,
                )
            )
            question.story_ref = None
        questions.append(question)

    for question in questions:
        issues += validate_rendered(question.answer_outline, context="An answer outline")

    prep = InterviewPrep(
        jd_id=jd.id or 0,
        interviewers=interviewers,
        questions=questions,
        questions_to_ask=_questions_to_ask(assessment, parsed),
        opening=str(parsed.get("opening", "")).strip(),
        prepared_at=prepared_at or datetime.now(timezone.utc),
    )
    return prep, issues


def _questions_to_ask(assessment: FitAssessment, parsed: dict) -> list[str]:
    """Alan's questions: the unresolved filters first, then the model's.

    An unanswered commute or salary question is not small talk — it is the
    thing that decides whether the role is viable at all, and it survives from
    the assessment into the room.
    """
    questions = list(assessment.questions_to_ask)
    for extra in parsed.get("questions_to_ask", []):
        text = str(extra).strip()
        if text and text not in questions:
            questions.append(text)
    return questions


def _render_stories(profile: Profile) -> str:
    lines = []
    for story in profile.stories.stories:
        lines.append(
            f"{story.id} — {story.label} "
            f"[{', '.join(story.question_types) or 'untagged'}]\n"
            f"  situation: {story.situation}\n"
            f"  task: {story.task}\n"
            f"  action: {story.action}\n"
            f"  result: {story.result}"
        )
        if story.what_id_do_differently:
            lines.append(f"  what he would do differently: {story.what_id_do_differently}")

    explanations = profile.stories.explanations.model_dump(exclude_none=True)
    if explanations:
        lines.append("\n## Agreed explanations — use these words, do not invent others")
        for key, value in explanations.items():
            if isinstance(value, str):
                lines.append(f"  {key}: {value}")
            elif isinstance(value, list):
                lines.append(f"  {key}: " + "; ".join(str(v) for v in value))
    return "\n".join(lines)


def _summary(jd: JobDescription) -> str:
    data = jd.model_dump(mode="json")
    data.pop("raw_text", None)
    return json.dumps(data, indent=2, ensure_ascii=False)


def _assessment(assessment: FitAssessment) -> str:
    data = assessment.model_dump(mode="json")
    for key in ("id", "jd_id", "model_used", "scored_at"):
        data.pop(key, None)
    return json.dumps(data, indent=2, ensure_ascii=False)


def _blocker():
    from jobagent.core.validation import Severity

    return Severity.blocker
