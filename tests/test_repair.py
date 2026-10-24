"""Repairing instead of rewriting: flagged sentences, and repetition dropped in code. Invented data."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jobagent.adapters.docx_writer import ResumeContent
from jobagent.core.generate import (
    GeneratedResume,
    GeneratedText,
    Sentence,
    _repair_repeats,
    _ResumeSelection,
    apply_resume_repairs,
    apply_text_repairs,
)
from jobagent.core.profile import load_profile
from jobagent.core.validation import Severity, ValidationIssue
from jobagent.services import checks


@pytest.fixture
def profile(example_dir):
    return load_profile(example_dir)


class FakeClient:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def complete_json(self, *, prompt, label, max_tokens):
        self.prompts.append(prompt)
        return self.answer, None


def test_repair_sentences_sends_only_the_flagged_ones_with_their_evidence(profile):
    role = profile.roles.roles[0]
    sentences = [Sentence(text="I gave them a year to pick.", cites=[f"{role.id}.0"]),
                 Sentence(text="An untouched sentence.", cites=[f"{role.id}.0"])]
    client = FakeClient({"repairs": [
        {"original": "I gave them a year to pick.", "text": "I gave them a couple of weeks to pick."},
        {"original": "Something never asked about.", "text": "x"},
    ]})
    out = checks.repair_sentences(
        None, None, [checks.Mismatch(sentence="I gave them a year to pick.", problem="invented sequence")],
        sentences, profile, client_factory=lambda: client)
    assert out == {"I gave them a year to pick.": "I gave them a couple of weeks to pick."}
    assert "An untouched sentence" not in client.prompts[0]
    assert role.bullets[0].text.split()[0] in client.prompts[0]  # the evidence went with it


def test_a_failed_repair_never_raises(profile):
    def broken():
        raise RuntimeError("no model")
    out = checks.repair_sentences(None, None, [checks.Mismatch(sentence="A.", problem="p")],
                                  [Sentence(text="A.", cites=["x.0"])], profile, client_factory=broken)
    assert isinstance(out, checks.NotChecked)


def test_letter_repairs_replace_the_sentence_and_run_the_code_checks_again():
    seen = []

    def recheck(paragraphs):
        seen.append(paragraphs)
        return [ValidationIssue(rule="banned phrase", severity=Severity.blocker, detail="x")] \
            if "thrilled" in paragraphs[0][0].text else []

    letter = GeneratedText(text="Old one. Two.", paragraphs=[[Sentence(text="Old one."), Sentence(text="Two.")]],
                           recheck=recheck)
    fixed = apply_text_repairs(letter, {"Old one.": "New one."})
    assert fixed.text == "New one. Two." and fixed.issues == [] and seen
    bad = apply_text_repairs(letter, {"Old one.": "I am thrilled."})
    assert bad.issues[0].rule == "banned phrase"


def test_resume_repairs_replace_a_highlight_keeping_its_form(profile):
    content = ResumeContent(name="A", tagline="t", contact="c", profile_paragraphs=["I lead teams."],
                            highlights=[("Founder, architect", "Built it alone.")], skills=[], roles=[],
                            earlier_career=[], education=[])
    built = GeneratedResume(content=content, sentences=[Sentence(text="Founder, architect — Built it alone.", cites=["x"])],
                            on_page={"highlight 1": "Built it alone."})
    fixed = apply_resume_repairs(built, {"Founder, architect — Built it alone.": "Co-founder & CTO — Built it alone."}, profile)
    assert fixed.content.highlights == [("Co-founder & CTO", "Built it alone.")]
    assert fixed.sentences[0].text == "Co-founder & CTO — Built it alone."
    assert built.content.highlights == [("Founder, architect", "Built it alone.")]  # the original is untouched


def test_a_bullet_repeating_a_highlight_is_dropped_but_never_a_roles_last(profile):
    role = next(r for r in profile.roles.roles if len(r.bullets) >= 2)
    other = next(r for r in profile.roles.roles if r.id != role.id)
    catalogue = {f"{role.id}.{i}": b.text for i, b in enumerate(role.bullets)}
    catalogue[f"{other.id}.0"] = other.bullets[0].text
    selection = _ResumeSelection(
        tagline="t", profile_paragraphs=["p"],
        highlights=[{"label": "L", "text": role.bullets[0].text, "source_ref": f"{role.id}.0"},
                    {"label": "M", "text": other.bullets[0].text, "source_ref": f"{other.id}.0"}],
        roles=[{"role_id": role.id, "bullet_refs": [f"{role.id}.0", f"{role.id}.1"]},
               {"role_id": other.id, "bullet_refs": [f"{other.id}.0"]}],
    )
    repaired, notes = _repair_repeats(selection, profile, catalogue)
    refs = {r.role_id: r.bullet_refs for r in repaired.roles}
    assert refs[role.id] == [f"{role.id}.1"]
    assert refs[other.id] == [f"{other.id}.0"]  # its only bullet stays
    assert any(f"{role.id}.0" in n for n in notes)
