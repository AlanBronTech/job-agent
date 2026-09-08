"""Checking generated prose against the rules in ``profile/voice.md``.

Three hard rules from CLAUDE.md land here, and this is the only place they are
enforced mechanically rather than asked for politely in a prompt:

* **No invented experience.** Every number in generated prose must appear
  somewhere in the profile. A fabricated metric is the failure that would cost
  Alan an interview, and unlike a fabricated adjective it is detectable.
* **Voice.** The banned-phrase list is read from ``voice.md`` at runtime rather
  than copied into Python, so editing the file changes the filter.
* **The age-signal policy.** Never state or compute a career length. This is
  the rule Alan is most exposed on — he is deliberately removing age as a
  screening signal — so it gets explicit patterns rather than a prompt
  instruction and a hope.

Nothing here calls a model. A validator that needs a model to decide is a
second opinion, not a check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from jobagent.core.models import Profile, Visibility


class Severity(str, Enum):
    """``blocker`` means do not send this without a human fixing it."""

    blocker = "blocker"
    warning = "warning"


@dataclass
class ValidationIssue:
    rule: str
    severity: Severity
    detail: str
    excerpt: str = ""


# Career length, in every form the policy names. These are the ones that matter
# most: two of Alan's own past letters open with exactly this phrasing.
_AGE_SIGNAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b\d{1,2}\s*\+?\s*years?\s+(?:of\s+)?(?:experience|in\s+(?:the\s+)?industry)",
     "states a total years-of-experience figure"),
    # Ten or more only. "Re-platformed incrementally over 2 years" is a
    # project duration and appears on the master resume; flagging it would
    # teach Alan to click past the blockers that matter. A smaller figure
    # attached to "experience" is still caught by the pattern above.
    (r"\bover\s+(?:1[0-9]|[2-9]\d)\s+years\b", "states a career length"),
    (r"\b(?:two|three|four)\s+decades\b", "states a career length in decades"),
    (r"\bdecades\s+of\s+experience\b", "states a career length in decades"),
    (r"\bsince\s+(?:19|20)\d{2}\b", "computes a career length from a start year"),
    (r"\bcareer\s+spanning\b", "states a career length"),
    (r"\b(?:my\s+)?first\s+role,?\s+back\s+in\b", "points at the start of the career"),
)

# Sentence openers voice.md bans by shape rather than by wording.
_BANNED_OPENERS = (
    "as a seasoned professional",
    "i am writing to apply for",
)

_NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Notes the profile keeps for its own bookkeeping, which read as gibberish on
# a resume. A real bullet ends "...for a Utrecht University researcher — see
# ai_capability.research_agent for evidence and current status", and copied
# verbatim it went onto the page.
_INTERNAL_REFERENCE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsee\s+[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", "points at another profile entry"),
    (r"\bsee\s+(?:roles|assets|stories)\.yaml", "points at a profile file"),
    (r"\bnote_for_scorer\b", "names an internal field"),
    (r"\bevidence_strength\b", "names an internal field"),
    (r"\bvisibility:\s*\w+", "names an internal field"),
)

# Numbers that carry no claim and would produce noise if traced.
_HARMLESS_NUMBERS = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}


def validate_prose(
    text: str,
    profile: Profile,
    *,
    max_words: int | None = None,
    context: str = "generated text",
) -> list[ValidationIssue]:
    """Check one piece of generated prose. Empty list means it passed."""
    issues: list[ValidationIssue] = []
    issues += _check_age_signals(text)
    issues += _check_banned_phrases(text, profile.voice)
    issues += _check_openers(text)
    issues += _check_numbers(text, profile)
    issues += _check_scorer_only_leakage(text, profile)
    if max_words is not None:
        issues += _check_length(text, max_words, context)
    return issues


def validate_rendered(text: str, *, context: str = "a bullet") -> list[ValidationIssue]:
    """Check text copied verbatim out of the profile onto a page.

    Narrower than `validate_prose`: the numbers are the profile's own, so
    tracing them is pointless, and the wording is Alan's. What matters is that
    the profile's internal bookkeeping — cross-references to other entries,
    field names — does not reach the reader, and that no bullet states a
    career length.
    """
    issues = _check_age_signals(text)
    for pattern, description in _INTERNAL_REFERENCE_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            issues.append(
                ValidationIssue(
                    rule="internal reference",
                    severity=Severity.blocker,
                    detail=(
                        f"{context} {description}, which means nothing to a "
                        "reader. Edit the bullet in the profile — it is being "
                        "copied verbatim."
                    ),
                    excerpt=_excerpt(text, match.start(), match.end()),
                )
            )
    return issues


def blockers(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.severity is Severity.blocker]


# --------------------------------------------------------------------------- #
# Individual rules
# --------------------------------------------------------------------------- #


def _check_age_signals(text: str) -> list[ValidationIssue]:
    issues = []
    for pattern, description in _AGE_SIGNAL_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            issues.append(
                ValidationIssue(
                    rule="age signal",
                    severity=Severity.blocker,
                    detail=(
                        f"Text {description}. voice.md forbids stating or "
                        "computing a career length in any form."
                    ),
                    excerpt=_excerpt(text, match.start(), match.end()),
                )
            )
    return issues


def _check_banned_phrases(text: str, voice: str) -> list[ValidationIssue]:
    lowered = text.lower()
    issues = []
    for phrase in banned_phrases(voice):
        index = lowered.find(phrase)
        if index != -1:
            issues.append(
                ValidationIssue(
                    rule="banned phrase",
                    severity=Severity.blocker,
                    detail=f"voice.md bans {phrase!r}.",
                    excerpt=_excerpt(text, index, index + len(phrase)),
                )
            )
    return issues


def _check_openers(text: str) -> list[ValidationIssue]:
    issues = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        stripped = sentence.strip().lower()
        for opener in _BANNED_OPENERS:
            if stripped.startswith(opener):
                issues.append(
                    ValidationIssue(
                        rule="banned opening",
                        severity=Severity.blocker,
                        detail=f"voice.md bans sentences opening {opener!r}.",
                        excerpt=sentence.strip()[:120],
                    )
                )
    return issues


def _check_numbers(text: str, profile: Profile) -> list[ValidationIssue]:
    """Every figure in generated prose must appear somewhere in the profile.

    This is the invented-experience check. It cannot catch a fabricated
    adjective, and does not try; it catches the fabricated metric, which is
    the one that ends an interview.
    """
    haystack = _profile_numbers(profile)
    issues = []
    for match in _NUMBER_PATTERN.finditer(text):
        raw = match.group()
        normalised = raw.replace(",", "")
        if normalised in _HARMLESS_NUMBERS or _looks_like_a_year(normalised):
            continue
        if normalised not in haystack:
            issues.append(
                ValidationIssue(
                    rule="unsupported number",
                    severity=Severity.blocker,
                    detail=(
                        f"The figure {raw!r} does not appear anywhere in the "
                        "profile. Either it is invented, or the profile is "
                        "missing the evidence for it."
                    ),
                    excerpt=_excerpt(text, match.start(), match.end()),
                )
            )
    return issues


def _check_scorer_only_leakage(text: str, profile: Profile) -> list[ValidationIssue]:
    """``scorer_only`` entries inform the decision and are never rendered."""
    lowered = text.lower()
    issues = []
    for label in _scorer_only_labels(profile):
        if len(label) > 8 and label.lower() in lowered:
            issues.append(
                ValidationIssue(
                    rule="scorer-only content",
                    severity=Severity.blocker,
                    detail=(
                        f"{label!r} is marked visibility: scorer_only in the "
                        "profile. It informs the decision and is never rendered."
                    ),
                    excerpt=label,
                )
            )
    return issues


def _check_length(text: str, max_words: int, context: str) -> list[ValidationIssue]:
    count = len(text.split())
    if count <= max_words:
        return []
    return [
        ValidationIssue(
            rule="length",
            severity=Severity.blocker,
            detail=f"{context} is {count} words against a {max_words}-word limit.",
        )
    ]


# --------------------------------------------------------------------------- #
# Reading the rules out of voice.md
# --------------------------------------------------------------------------- #


def banned_phrases(voice: str) -> list[str]:
    """The literal phrases under "## Banned phrases" in voice.md, lowercased.

    Entries read as alternates around a slash — "I am thrilled / excited /
    delighted / passionate about" — or around a comma — "results-driven,
    detail-oriented, team player, go-getter" — so each fragment is taken as
    its own phrase. Entries phrased as a rule rather than a phrase ("Any
    sentence beginning…") are skipped here; they are judgment, and the ones
    worth mechanising have explicit checks above.
    """
    section = _section(voice, "Banned phrases")
    phrases: list[str] = []
    for line in section.splitlines():
        if not line.strip().startswith("-"):
            continue
        entry = line.strip().lstrip("-").strip()
        entry = re.sub(r"\([^)]*\)", "", entry).strip()  # drop qualifiers
        if entry.lower().startswith("any "):
            continue
        for alternate in re.split(r"\s+/\s+|,\s+", entry):
            cleaned = alternate.strip().strip(".,").lower()
            if len(cleaned) >= 5:
                phrases.append(cleaned)
    return phrases


def _section(voice: str, heading: str) -> str:
    """The body of one `## heading` section of voice.md."""
    pattern = rf"^##\s+{re.escape(heading)}.*?$(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, voice, flags=re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


# --------------------------------------------------------------------------- #
# Profile facts
# --------------------------------------------------------------------------- #


def _profile_numbers(profile: Profile) -> set[str]:
    """Every number the profile offers as evidence for a claim.

    This set is what licenses a figure in generated prose, so what is left out
    of it matters as much as what goes in. It is built by walking the loaded
    model rather than listing fields by hand: the hand-written list this
    replaced had already drifted from the schema, omitting
    ``stories.explanations`` — which ``generate.py`` feeds to the cover-letter
    and answers prompts under "use these words, do not invent others". A model
    following that instruction exactly had its salary expectation blocked as an
    invented figure.
    """
    found: set[str] = set()
    for text in _evidence_text(profile):
        for match in _NUMBER_PATTERN.finditer(text):
            found.add(match.group().replace(",", ""))
    return found


# Keys whose contents are in the profile but are not evidence for anything Alan
# can claim. Everything else is included, so a field added to the schema is
# covered without editing this file.
#
#   voice            the rules document, not evidence. It quotes "25 years" and
#                    "20+ years" as examples of *banned* age signals and states
#                    Alan's age; scanning it made all three supported numbers.
#   note_for_scorer  bookkeeping the model never sees when generating. Two
#                    figures live only here — the DataLlama user count and the
#                    HDD equity split — and the profile says in as many words
#                    that neither is ever to be published. A haystack covering
#                    them would have this check bless the one number the
#                    profile forbids.
#   phone            rendered onto the contact line deterministically, never
#                    through generated prose. Its digits are not evidence, and
#                    including them licensed "379" as a headcount.
#   *_rationale      why a filter is set, not a claim about Alan.
#
# Entries marked ``visibility: scorer_only`` are skipped for the same reason as
# ``note_for_scorer``: they inform the decision and are never rendered.
_NON_EVIDENCE_KEYS = frozenset({"voice", "note_for_scorer", "phone"})


def _evidence_text(profile: Profile) -> list[str]:
    """Every string in the profile that may support a figure in prose."""
    found: list[str] = []
    _collect(profile.model_dump(mode="json"), found)
    return found


def _collect(node: object, found: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("visibility") == Visibility.scorer_only.value:
            return
        for key, value in node.items():
            if key in _NON_EVIDENCE_KEYS or key.endswith("_rationale"):
                continue
            _collect(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect(item, found)
    elif node is not None:
        found.append(str(node))


def _scorer_only_labels(profile: Profile) -> list[str]:
    labels = []
    for entry in profile.roles.ai_capability:
        if entry.visibility is Visibility.scorer_only:
            labels.append(entry.label)
    for entry in profile.roles.founder_track_record:
        if entry.visibility is Visibility.scorer_only:
            labels.append(entry.company)
    for role in profile.roles.roles:
        if role.visibility is Visibility.scorer_only:
            labels.append(role.company)
    return labels


def _looks_like_a_year(value: str) -> bool:
    """Role dates are permitted; it is summing them that is banned, and the
    age-signal patterns above catch the summing."""
    return bool(re.fullmatch(r"(?:19|20)\d{2}", value))


def _excerpt(text: str, start: int, end: int, window: int = 40) -> str:
    left = max(0, start - window)
    right = min(len(text), end + window)
    return ("…" if left else "") + text[left:right].strip() + ("…" if right < len(text) else "")
