"""How far a sent document is from the one `generate` wrote.

The goal this measures (REVIEW-2026-10-18): the documents sent are the
documents generated. Until it is counted, "almost nothing goes out as
generated" is a feeling; the first pair measured, Macquarie, kept about half
of each document.

Pure: sections in, numbers and sentences out. Reading a .docx into sections is
`adapters/docx_reader`.

Two measures, because they answer different questions:

* **Kept share** is word-level: of the words generated, how many survive, in
  order, into the sent version. Moving a paragraph costs it; fixing one word
  in a long bullet barely does. Computed over the whole document as well as
  per section, because a renamed heading would otherwise count every word
  under it as lost.
* **Sentences** added, removed and changed are what a person reads to decide
  what kind of edit each was — a defect, a missing fact, a preference, or
  something only Alan knew. That classification is deliberately not done
  here; the first batch is read by hand before any table is built for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# A removed and an added sentence this similar are one sentence, edited.
CHANGED_RATIO = 0.6

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“‘(])")


@dataclass
class Section:
    name: str
    paragraphs: list[str]

    @property
    def text(self) -> str:
        return " ".join(self.paragraphs)


@dataclass
class SectionDiff:
    name: str
    generated_words: int
    sent_words: int
    kept_words: int
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[tuple[str, str]] = field(default_factory=list)  # (generated, sent)

    @property
    def kept_share(self) -> float | None:
        """None for a section only the sent version has."""
        return self.kept_words / self.generated_words if self.generated_words else None

    @property
    def unchanged(self) -> bool:
        return not (self.added or self.removed or self.changed) and (
            self.generated_words == self.sent_words == self.kept_words
        )


@dataclass
class DocumentDiff:
    generated_words: int
    sent_words: int
    kept_words: int
    sections: list[SectionDiff]

    @property
    def kept_share(self) -> float | None:
        return self.kept_words / self.generated_words if self.generated_words else None

    @property
    def unchanged(self) -> bool:
        return all(section.unchanged for section in self.sections) and (
            self.generated_words == self.sent_words == self.kept_words
        )


def compare(generated: list[Section], sent: list[Section]) -> DocumentDiff:
    """Compare two documents section by section, matching sections by name.

    A section in only one of them is reported whole: everything in it added,
    or everything removed. Order follows the generated document, with
    sections only the sent one has after it.
    """
    sent_by_name = {section.name: section for section in sent}
    generated_names = {section.name for section in generated}
    sections = [
        compare_section(section, sent_by_name.get(section.name, Section(section.name, [])))
        for section in generated
    ]
    sections += [
        compare_section(Section(section.name, []), section)
        for section in sent
        if section.name not in generated_names
    ]
    whole_generated = words(" ".join(section.text for section in generated))
    whole_sent = words(" ".join(section.text for section in sent))
    return DocumentDiff(
        generated_words=len(whole_generated),
        sent_words=len(whole_sent),
        kept_words=_kept(whole_generated, whole_sent),
        sections=sections,
    )


def compare_section(generated: Section, sent: Section) -> SectionDiff:
    before, after = words(generated.text), words(sent.text)
    old = sentences(generated.paragraphs)
    new = sentences(sent.paragraphs)
    removed = [s for s in old if s not in new]
    added = [s for s in new if s not in old]
    changed: list[tuple[str, str]] = []
    for sentence in list(removed):
        best, ratio = None, CHANGED_RATIO
        for candidate in added:
            score = SequenceMatcher(None, sentence, candidate, autojunk=False).ratio()
            if score >= ratio:
                best, ratio = candidate, score
        if best is not None:
            changed.append((sentence, best))
            removed.remove(sentence)
            added.remove(best)
    return SectionDiff(
        name=generated.name or sent.name,
        generated_words=len(before),
        sent_words=len(after),
        kept_words=_kept(before, after),
        added=added,
        removed=removed,
        changed=changed,
    )


def words(text: str) -> list[str]:
    """Whitespace-separated, case and punctuation kept: a fixed comma is an edit."""
    return text.split()


def sentences(paragraphs: list[str]) -> list[str]:
    """Every paragraph is at least one sentence; a bullet has no full stop to split on."""
    out: list[str] = []
    for paragraph in paragraphs:
        text = " ".join(paragraph.split())
        out += [part for part in _SENTENCE_END.split(text) if part]
    return out


def _kept(before: list[str], after: list[str]) -> int:
    if not before or not after:
        return 0
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks())
