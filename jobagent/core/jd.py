"""Turning raw job-ad text into a validated ``JobDescription``.

The LLM client is injected rather than constructed here, so this module stays
callable from a test with a fake client, and from a web handler with a
differently-configured one. Nothing here reads config, prints, or exits.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

from jobagent.adapters.llm import LLMClient, LLMError
from jobagent.core.models import JobDescription
from jobagent.core.prompts import PromptError, load_prompt

PROMPT_NAME = "parse_jd"

# A long ad — the DiUS consulting JD has 23 requirement bullets — produces
# more than the 4,096-token default in structured output, and a truncated
# answer is unparseable JSON. Measured, not guessed: three calls came back at
# exactly 4,096 output tokens before this was raised.
MAX_TOKENS = 8192

MIN_TEXT_LENGTH = 120

# Keys the prompt is contracted to return. Anything else the model volunteers
# is dropped rather than passed to a model with extra="forbid", which would
# fail the whole parse over a stray field.
_EXPECTED_KEYS = frozenset(
    {
        "title",
        "company",
        "location",
        "work_type",
        "work_arrangement",
        "salary_range",
        "seniority",
        "posted_by",
        "via_agency",
        "hiring_status",
        "multiple_roles",
        "must_haves",
        "nice_to_haves",
        "tech_stack",
        "responsibilities",
        "red_flags",
    }
)


class JDError(Exception):
    """The text could not be parsed into a usable JobDescription."""


def parse_jd(
    raw_text: str,
    *,
    client: LLMClient,
    source: str | None = None,
    ingested_at: datetime | None = None,
) -> JobDescription:
    """Parse job-ad text into a ``JobDescription``.

    ``raw_text`` is preserved verbatim on the result — every downstream claim
    has to be checkable against the source, and re-parsing after a prompt
    change needs the original.
    """
    text = raw_text.strip()
    if not text:
        raise JDError("No job description text supplied.")
    if len(text) < MIN_TEXT_LENGTH:
        raise JDError(
            f"Job description is only {len(text)} characters — expected at least "
            f"{MIN_TEXT_LENGTH}. Paste the full advertisement, not just the title."
        )

    try:
        prompt = load_prompt(PROMPT_NAME, jd_text=text)
    except PromptError as exc:
        raise JDError(str(exc)) from exc

    try:
        parsed, _response = client.complete_json(
            prompt=prompt, label=PROMPT_NAME, max_tokens=MAX_TOKENS
        )
    except LLMError as exc:
        raise JDError(f"Model call failed while parsing the JD: {exc}") from exc

    if not isinstance(parsed, dict):
        raise JDError(
            f"Expected a JSON object from {PROMPT_NAME}, got {type(parsed).__name__}."
        )

    data = {key: value for key, value in parsed.items() if key in _EXPECTED_KEYS}
    data["raw_text"] = raw_text
    data["source"] = source
    data["ingested_at"] = ingested_at or datetime.now(timezone.utc)

    # A JD with no title is not usable downstream, and an empty string would
    # pass the model's `str` check while breaking every later display.
    if not str(data.get("title") or "").strip():
        raise JDError(
            "The model returned no job title. The text may not be a job "
            "advertisement, or may be truncated."
        )

    try:
        return JobDescription.model_validate(data)
    except ValidationError as exc:
        raise JDError(
            f"The model's output did not match the JobDescription schema. "
            f"This usually means prompts/{PROMPT_NAME}.md and core/models.py have "
            f"drifted apart.\n{exc}"
        ) from exc
