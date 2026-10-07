"""The two paid checks after generation (spec 003): claims and an independent review.

Both are judgement on top of the code checks, never instead of them, and
neither can lose the documents: a check that fails or times out returns
`NotChecked` / `NotReviewed`, the documents are written anyway, and they are
never called ready. Each call is logged like every other, under its own label,
so `jobagent spend` can say what the checks cost.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jobagent.adapters.llm import CallType, RunContext, get_client
from jobagent.core.generate import Sentence, evidence_text
from jobagent.core.models import Profile
from jobagent.core.prompts import load_prompt
from jobagent.core.validation import AD

CLAIMS_PROMPT = "check_claims"
REVIEW_PROMPT = "review_documents"
POLICIES_PROMPT = "review_policies"
MAX_TOKENS = 4096


@dataclass(frozen=True)
class NotChecked:
    reason: str


@dataclass(frozen=True)
class NotReviewed:
    reason: str


class Mismatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sentence: str
    problem: str


class _Mismatches(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mismatches: list[Mismatch] = Field(default_factory=list)


def claims_block(sentences: list[Sentence], profile: Profile) -> str | None:
    """Each sentence with the text of what it cites. None when nothing to check."""
    blocks = []
    for sentence in sentences:
        refs = [ref for ref in sentence.cites if ref != AD]
        if not refs:
            continue
        lines = [f"SENTENCE: {sentence.text}"]
        for ref in refs:
            lines.append(f"  [{ref}] {evidence_text(profile, ref) or '(no such evidence)'}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or None


def check_claims(
    config,
    ctx: RunContext,
    sentences: list[Sentence],
    profile: Profile,
    *,
    client_factory: Callable[[], object] | None = None,
) -> list[Mismatch] | NotChecked:
    """Each cited sentence against its evidence. Never raises on a model failure."""
    claims = claims_block(sentences, profile)
    if claims is None:
        return []
    try:
        client = (client_factory or (lambda: get_client(CallType.review, config, ctx)))()
        parsed, _ = client.complete_json(
            prompt=load_prompt(CLAIMS_PROMPT, claims=claims),
            label=CLAIMS_PROMPT,
            max_tokens=MAX_TOKENS,
        )
        return _Mismatches.model_validate(parsed).mismatches
    except ValidationError as exc:
        return NotChecked(f"the answer did not match the contract: {exc.error_count()} error(s)")
    except Exception as exc:  # noqa: BLE001 - a failed check never loses the documents
        return NotChecked(str(exc))
