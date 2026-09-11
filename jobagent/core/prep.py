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

import re

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
from jobagent.core.validation import Severity, ValidationIssue, validate_rendered

_QUESTION_KEYS = frozenset(PrepQuestion.model_fields)

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

    # The assessment's challenge points are NOT injected as finished questions
    # any more. They were, and it produced the worst section of three real prep
    # documents in a row: `challenge.point` is a topic the scorer wrote for a
    # reader ("Whether he has built AI products at enterprise scale versus
    # adopted AI tools personally") and `challenge.response` is prose written
    # *about* Alan ("the honest answer is that he has not used either named
    # framework"). Printed under "The hard ones" they read as neither questions
    # nor answers, and one carried `stories.explanations.why_leaving_current`
    # verbatim into a document he would have open in an interview.
    #
    # The model now writes them, in his voice, from the same challenge points —
    # it already receives them in `assessment_json`. Coverage was structural and
    # is now checked instead: see `_check_challenge_coverage`.

    for entry in parsed.get("questions", []):
        try:
            question = PrepQuestion.model_validate(_contracted(entry))
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

    issues += _check_challenge_coverage(assessment, questions)

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


def _check_challenge_coverage(
    assessment: FitAssessment, questions: list[PrepQuestion]
) -> list[ValidationIssue]:
    """Report when the model wrote fewer hard questions than the scorer found.

    The gaps the scorer identified used to be guaranteed a place by being
    injected verbatim. They are written by the model now, so the guarantee is
    weaker — this is what replaces it. A warning, not a blocker: it cannot tell
    whether a hard question *addresses* a given challenge point, only that
    fewer were written than there were gaps to cover.
    """
    wanted = len(assessment.challenge_points)
    got = sum(1 for question in questions if question.hard)
    if not wanted or got >= wanted:
        return []
    return [
        ValidationIssue(
            rule="challenge coverage",
            severity=Severity.warning,
            detail=(
                f"The assessment found {wanted} challenge point(s) and the prep "
                f"has {got} hard question(s). Check the gaps it flagged are "
                "actually answered before relying on this."
            ),
        )
    ]


def _contracted(entry: object) -> object:
    """Drop keys `PrepQuestion` does not declare, before validating.

    The models set ``extra="forbid"``, so one volunteered field fails the whole
    prep — a real run died on an ``answer_outline_note`` the prompt never asked
    for, after the questions had already been written and paid for. `jd.py` has
    dropped unknown keys from the parser's output for the same reason since
    Phase 1; this is that treatment, applied where it was missing.

    The key set is read off the model rather than hand-listed. A hand-written
    copy of a model's fields drifts from it — that is how the number haystack
    in `validation.py` came to be missing four of them.
    """
    if not isinstance(entry, dict):
        return entry
    return {key: value for key, value in entry.items() if key in _QUESTION_KEYS}


def _questions_to_ask(assessment: FitAssessment, parsed: dict) -> list[str]:
    """Alan's questions: the unresolved filters first, then the model's.

    An unanswered commute or salary question is not small talk — it is the
    thing that decides whether the role is viable at all, and it survives from
    the assessment into the room.
    """
    questions: list[str] = []
    seen: set[str] = set()
    for text in [*assessment.questions_to_ask, *parsed.get("questions_to_ask", [])]:
        text = str(text).strip()
        # Normalised so punctuation, case and word order do not produce two
        # copies of one question. It does NOT catch a rephrasing, and one real
        # run listed four near-identical pairs that survive this: "…or is it a
        # capability-building function embedded in existing teams?" against
        # "…or is the team being built out, and at what pace?" share 8 words of
        # 29. Any threshold loose enough to merge those merges questions that
        # are genuinely different, so the rephrasing case is handled in the
        # prompt instead, where the model is told not to restate the
        # assessment's own questions.
        key = " ".join(sorted(re.findall(r"[a-z0-9]+", text.lower())))
        if text and key not in seen:
            seen.add(key)
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
