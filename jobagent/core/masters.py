"""The master-resume registry: which hand-written resumes exist, and what each is for.

Alan keeps a small set of approved master resumes and sends one per ad
instead of composing a new resume every time (REVIEW-2026-11-14). They live in
`<profile>/resumes/`, gitignored with the rest of the profile, and
`masters.yaml` in that folder lists them. This module only loads and checks
that list. Choosing a master for an ad is a separate step.

The registry is optional. Without it there are no masters and `generate`
works as before; a custom resume stays available either way.

Pure logic: raises `ProfileError` with a message meant for a human, so the CLI
and the web UI report a bad registry the same way they report a bad profile.
"""

from __future__ import annotations

from pathlib import Path

from jobagent.core.models import MasterResume, MastersFile
from jobagent.core.profile import ProfileError, _load_yaml, _parse_model

RESUMES_DIR = "resumes"
MASTERS_FILE = "masters.yaml"


def load_masters(profile_dir: str | Path) -> list[MasterResume]:
    """The masters listed in `<profile_dir>/resumes/masters.yaml`, in file order.

    Returns an empty list when there is no registry. Raises `ProfileError`
    when there is one and it is wrong: bad YAML, an unknown key or value, a
    duplicate id, not exactly one default, or a document that is not there.
    """
    folder = Path(profile_dir) / RESUMES_DIR
    path = folder / MASTERS_FILE
    if not path.exists():
        return []

    parsed: MastersFile = _parse_model(MastersFile, _load_yaml(path), MASTERS_FILE)
    entries = parsed.masters
    if not entries:
        raise ProfileError(f"{MASTERS_FILE}: lists no masters. Add one, or delete the file.")

    errors: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            errors.append(f"id {entry.id!r} is used twice")
        seen.add(entry.id)
        if not entry.docx.lower().endswith(".docx"):
            errors.append(f"{entry.id}: docx must name a .docx file, got {entry.docx!r}")
        if entry.pdf is not None and not entry.pdf.lower().endswith(".pdf"):
            errors.append(f"{entry.id}: pdf must name a .pdf file, got {entry.pdf!r}")
        for name in (entry.docx, entry.pdf):
            if name is not None and not (folder / name).is_file():
                errors.append(f"{entry.id}: {name} is not in {folder}")

    defaults = [e.id for e in entries if e.default]
    if len(defaults) != 1:
        found = ", ".join(defaults) if defaults else "none"
        errors.append(f"exactly one master must be the default (found: {found})")

    if errors:
        raise ProfileError(
            f"{MASTERS_FILE}: {len(errors)} problem(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return [
        MasterResume(
            **entry.model_dump(exclude={"docx", "pdf"}),
            docx=folder / entry.docx,
            pdf=folder / entry.pdf if entry.pdf else None,
        )
        for entry in entries
    ]
