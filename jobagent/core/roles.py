"""The kind of role an ad is, and what that does to the evidence (spec 003).

Three things follow from an ad's kind, and two are enforced here in code:

* **Exclusions.** A story, entry or bullet can declare the kinds it must not
  appear for in written documents. `excluded_ids` names everything that falls
  out — including a bullet whose `linked_story` is excluded, since the bullet
  *is* that story told in one line. The generator leaves these out of what the
  writer is shown, then re-checks the output: a rule that only forbids gets
  satisfied by rephrasing, and evidence the writer never saw cannot be used.
  Interview prep ignores exclusions; the question will still come.
* **Skills order.** `order_skills` sorts the selected skill categories by kind.
* **What leads.** Per-kind guidance is in the writer prompts; `lead_issue`
  reports, as a warning, a first highlight whose evidence is not of the kind.
  Tags are coarse, so it informs rather than blocks.

Ids stay stable: bullets are skipped, never removed and renumbered, so
`recent_manager.3` means the same bullet to the assessment, the catalogue and
the checks.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from jobagent.adapters.llm import LLMClient, LLMError
from jobagent.core.models import JobDescription, Profile, RoleClassification, RoleKind
from jobagent.core.prompts import PromptError, load_prompt

CLASSIFY_PROMPT = "classify_role"
CLASSIFY_MAX_TOKENS = 1024


class ClassifyError(Exception):
    """The classifier's answer could not be used."""


def classify(jd: JobDescription, *, client: LLMClient) -> RoleClassification:
    """One small call: the parsed ad in, a kind and a one-sentence reason out."""
    import json

    ad = {
        "title": jd.title,
        "must_haves": jd.must_haves,
        "responsibilities": jd.responsibilities,
        "nice_to_haves": jd.nice_to_haves,
    }
    try:
        prompt = load_prompt(CLASSIFY_PROMPT, ad_json=json.dumps(ad, indent=2, ensure_ascii=False))
    except PromptError as exc:
        raise ClassifyError(str(exc)) from exc
    try:
        parsed, _ = client.complete_json(
            prompt=prompt, label=CLASSIFY_PROMPT, max_tokens=CLASSIFY_MAX_TOKENS
        )
    except LLMError as exc:
        raise ClassifyError(f"Model call failed while classifying: {exc}") from exc
    if isinstance(parsed, dict):
        parsed = {k: v for k, v in parsed.items() if k in ("primary", "secondary", "reason")}
        if parsed.get("secondary") == parsed.get("primary"):
            parsed["secondary"] = None
    try:
        return RoleClassification.model_validate(parsed)
    except ValidationError as exc:
        raise ClassifyError(f"The classification did not match the contract.\n{exc}") from exc


# --------------------------------------------------------------------------- #
# Exclusions
# --------------------------------------------------------------------------- #


def kinds_of(classification: RoleClassification | None) -> set[RoleKind]:
    """Primary and secondary: exclusions for either apply."""
    return set(classification.kinds) if classification else set()


def excluded_ids(profile: Profile, kinds: Iterable[RoleKind]) -> set[str]:
    """Every story id, entry id and `entry.index` bullet id excluded for `kinds`."""
    kinds = set(kinds)
    if not kinds:
        return set()
    out: set[str] = set()
    for story in profile.stories.stories:
        if kinds & set(story.exclude_for):
            out.add(story.id)
    roles = profile.roles
    for group in (roles.roles, roles.founder_track_record, roles.ai_capability):
        for entry in group:
            entry_out = bool(kinds & set(entry.exclude_for))
            if entry_out:
                out.add(entry.id)
            for index, bullet in enumerate(entry.bullets):
                if (
                    entry_out
                    or kinds & set(bullet.exclude_for)
                    or (bullet.linked_story and bullet.linked_story in out)
                ):
                    out.add(f"{entry.id}.{index}")
    for entry in roles.earlier_career:
        if kinds & set(entry.exclude_for):
            out.add(entry.id)
    return out


def is_excluded(ref: str, excluded: set[str]) -> bool:
    """A ref is out if it, or the entry it belongs to, is excluded."""
    return ref in excluded or ref.split(".", 1)[0] in excluded


# --------------------------------------------------------------------------- #
# Skills order and the lead
# --------------------------------------------------------------------------- #

# Skill-category keys in the order each kind wants them; categories not listed
# keep the model's order after these. Keys are profile.yaml `skills:` keys.
SKILL_ORDER: dict[RoleKind, list[str]] = {
    RoleKind.people_focused: ["leadership", "delivery"],
    RoleKind.delivery_focused: ["delivery", "leadership"],
    RoleKind.technical_lead: [
        "backend_and_apis",
        "cloud_and_devops",
        "data",
        "frontend",
        "ai_and_automation",
    ],
    RoleKind.ai_enablement: ["ai_and_automation", "backend_and_apis", "cloud_and_devops"],
}

# Bullet tags that make a first highlight "on-kind".
LEAD_TAGS: dict[RoleKind, set[str]] = {
    RoleKind.people_focused: {"leadership", "hiring"},
    RoleKind.delivery_focused: {"delivery", "agile_transformation", "stakeholder_management"},
    RoleKind.technical_lead: {"architecture", "replatforming", "full_stack", "cicd"},
    RoleKind.ai_enablement: {"ai_adoption", "agent_development"},
}

# Tags that make a people-focused lead off-kind even when it also says
# leadership: an AI highlight first was the worked example's second fault.
_OFF_LEAD: dict[RoleKind, set[str]] = {
    RoleKind.people_focused: {"ai_adoption", "agent_development"},
}


def order_skills(keys: list[str], kind: RoleKind | None) -> list[str]:
    if kind is None:
        return list(keys)
    wanted = SKILL_ORDER.get(kind, [])
    rank = {key: index for index, key in enumerate(wanted)}
    return sorted(keys, key=lambda k: (rank.get(k, len(wanted)), keys.index(k)))


def tags_of(ref: str, profile: Profile) -> set[str]:
    """The tags behind a cited id: one bullet's, or every bullet's of an entry."""
    entry_id, _, index = ref.partition(".")
    roles = profile.roles
    for group in (roles.roles, roles.founder_track_record, roles.ai_capability):
        for entry in group:
            if entry.id != entry_id:
                continue
            if index.isdigit() and int(index) < len(entry.bullets):
                return set(entry.bullets[int(index)].tags)
            return {tag for bullet in entry.bullets for tag in bullet.tags}
    for entry in roles.earlier_career:
        if entry.id == entry_id:
            return set(entry.tags)
    return set()


def lead_is_on_kind(ref: str, profile: Profile, kind: RoleKind) -> bool:
    tags = tags_of(ref, profile)
    return bool(tags & LEAD_TAGS[kind]) and not (tags & _OFF_LEAD.get(kind, set()))
