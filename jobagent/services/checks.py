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
# Generous for the same reason as the resume's ceiling: the count includes the
# model's reasoning. The first real review (2026-10-07) hit 4,096
# with a short answer still unwritten, and was lost.
MAX_TOKENS = 16384


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


class Finding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document: str = ""
    finding: str


class Review(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blocking: list[Finding] = Field(default_factory=list)
    suggestions: list[Finding] = Field(default_factory=list)


def review_prompt(jd, documents: dict[str, str], *, kind, excluded: list[str], banned: list[str]) -> str:
    """The reviewer's whole input: the parsed ad, the policies, the documents.

    Deliberately not the writer prompts, the catalogue or any scorer note: a
    reviewer reading the instructions marks against them, not against the ad.
    """
    from jobagent.core.generate import _jd_summary, role_kind_block

    return load_prompt(
        REVIEW_PROMPT,
        ad_json=_jd_summary(jd),
        role_kind=role_kind_block(kind),
        excluded="\n".join(f"- {item}" for item in excluded) or "(none)",
        policies=load_prompt(POLICIES_PROMPT),
        banned=", ".join(f'"{phrase}"' for phrase in banned) or "(none)",
        documents="\n\n".join(
            f"=== {name} ===\n{text}" for name, text in documents.items()
        ),
    )


def excluded_descriptions(profile: Profile, excluded: set[str]) -> list[str]:
    """What the excluded ids say, so the reviewer can recognise them in prose."""
    out = []
    for story in profile.stories.stories:
        if story.id in excluded:
            out.append(f"story: {story.label}")
    r = profile.roles
    for group in (r.roles, r.founder_track_record, r.ai_capability):
        for entry in group:
            for index, bullet in enumerate(entry.bullets):
                if f"{entry.id}.{index}" in excluded:
                    out.append(f"bullet: {bullet.text.strip()}")
    return out


def review(
    config,
    ctx: RunContext,
    jd,
    documents: dict[str, str],
    *,
    kind=None,
    excluded: list[str] = (),
    banned: list[str] = (),
    client_factory: Callable[[], object] | None = None,
) -> Review | NotReviewed:
    """The independent review. Never raises on a model failure."""
    if not documents:
        return NotReviewed("no documents")
    try:
        client = (client_factory or (lambda: get_client(CallType.review, config, ctx)))()
        parsed, _ = client.complete_json(
            prompt=review_prompt(jd, documents, kind=kind, excluded=list(excluded), banned=list(banned)),
            label=REVIEW_PROMPT,
            max_tokens=MAX_TOKENS,
        )
        return Review.model_validate(parsed)
    except ValidationError as exc:
        return NotReviewed(f"the answer did not match the contract: {exc.error_count()} error(s)")
    except Exception as exc:  # noqa: BLE001 - a failed review never loses the documents
        return NotReviewed(str(exc))


def review_markdown(result: Review | NotReviewed) -> str:
    """`review.md`, kept in the application folder beside the documents."""
    if isinstance(result, NotReviewed):
        return f"# Review\n\nNot reviewed: {result.reason}\n"
    lines = ["# Review", ""]
    lines.append("**Not ready.**" if result.blocking else "**Ready.** No blocking findings.")
    for title, findings in (("Blocking", result.blocking), ("Suggestions", result.suggestions)):
        if findings:
            lines += ["", f"## {title}", ""]
            lines += [f"- **{f.document or 'documents'}**: {f.finding}" for f in findings]
    return "\n".join(lines) + "\n"
