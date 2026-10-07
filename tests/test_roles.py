"""core.roles: exclusions with stable ids, skills order, the lead check, classify."""

from __future__ import annotations

import pytest

from jobagent.adapters.llm import LLMError
from jobagent.core import roles
from jobagent.core.models import RoleClassification, RoleKind
from jobagent.core.profile import load_profile
from tests.conftest import edit_yaml
from tests.quality_seed import RoutedClient, northwind


@pytest.fixture
def profile(example_dir):
    return load_profile(example_dir)


def test_an_excluded_story_takes_its_linked_bullet_with_it(profile):
    out = roles.excluded_ids(profile, {RoleKind.people_focused})
    assert "underperformer" in out
    assert "recent_manager.3" in out
    # Its neighbours keep their ids: nothing is renumbered.
    assert "recent_manager.0" not in out and "recent_manager.2" not in out


def test_no_kind_excludes_nothing(profile):
    assert roles.excluded_ids(profile, set()) == set()
    assert roles.excluded_ids(profile, {RoleKind.technical_lead}) == set()


def test_the_secondary_kind_excludes_too(profile):
    kind = RoleClassification(primary=RoleKind.technical_lead,
                              secondary=RoleKind.people_focused, reason="x")
    assert "underperformer" in roles.excluded_ids(profile, roles.kinds_of(kind))


def test_an_excluded_entry_takes_every_bullet(profile_factory):
    def mutate(path):
        def change(data):
            data["roles"][1]["exclude_for"] = ["technical_lead"]
        edit_yaml(path / "roles.yaml", change)

    profile = load_profile(profile_factory(mutate))
    entry = profile.roles.roles[1]
    out = roles.excluded_ids(profile, {RoleKind.technical_lead})
    assert entry.id in out
    assert all(f"{entry.id}.{i}" in out for i in range(len(entry.bullets)))
    assert roles.is_excluded(f"{entry.id}.0", {entry.id})


def test_skills_order_by_kind_keeps_the_rest_in_the_models_order():
    keys = ["ai_and_automation", "frontend", "delivery", "leadership"]
    assert roles.order_skills(keys, RoleKind.people_focused) == [
        "leadership", "delivery", "ai_and_automation", "frontend"]
    assert roles.order_skills(keys, None) == keys


def test_the_lead_check(profile):
    assert roles.lead_is_on_kind("recent_manager.0", profile, RoleKind.people_focused)
    # Leadership-tagged but an AI rollout: not a people-focused lead.
    assert not roles.lead_is_on_kind("recent_manager.1", profile, RoleKind.people_focused)


def test_classify_reads_the_parsed_ad_not_the_raw_text():
    client = RoutedClient({"classify_role": {
        "primary": "people_focused", "secondary": "people_focused",
        "reason": "Coaching leads.", "confidence": "high"}})
    kind = roles.classify(northwind(), client=client)
    assert kind.primary is RoleKind.people_focused
    assert kind.secondary is None  # a repeat of the primary is no secondary
    prompt = client.prompts["classify_role"][0]
    assert "Coaching and growing engineers" in prompt
    assert "route planning" not in prompt  # raw text stays out


def test_a_bad_classification_is_an_error():
    with pytest.raises(roles.ClassifyError):
        roles.classify(northwind(), client=RoutedClient({"classify_role": {"primary": "chef"}}))
    with pytest.raises(roles.ClassifyError):
        roles.classify(northwind(), client=RoutedClient({"classify_role": LLMError("down")}))
