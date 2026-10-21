"""Revision notes that recur: candidates for a rule rather than a note.

A note given once is about one application. The same note across three is
about the tool — a voice preference, a missing profile fact, or a defect —
and should be fixed where it starts, so it never has to be given again
(REVIEW-2026-10-18, task 2). This only groups and counts; Alan decides what a
recurring note becomes, and edits the profile or `voice.md` by hand.

Grouping is by shared words, which is crude on purpose: "lead with payments"
and "put the payments work first" belong together and share one word that
matters. A false group costs a glance; a model call per report costs money
for a list Alan reads in a minute.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jobagent.core.generate import overlap
from jobagent.core.models import RevisionNote

# Notes sharing this share of the shorter one's words are the same request.
SAME_REQUEST = 0.5
# Across this many applications a note is a rule waiting to be written.
RECURRING = 3


@dataclass
class NoteGroup:
    notes: list[RevisionNote] = field(default_factory=list)

    @property
    def applications(self) -> int:
        return len({note.jd_id for note in self.notes})

    @property
    def recurring(self) -> bool:
        return self.applications >= RECURRING


def group(notes: list[RevisionNote]) -> list[NoteGroup]:
    """Each note joins the first group it resembles; recurring groups first."""
    groups: list[NoteGroup] = []
    for note in notes:
        home = next(
            (g for g in groups if any(overlap(note.note, n.note) >= SAME_REQUEST for n in g.notes)),
            None,
        )
        if home is None:
            home = NoteGroup()
            groups.append(home)
        home.notes.append(note)
    return sorted(groups, key=lambda g: (-g.applications, -len(g.notes)))
