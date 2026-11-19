"""Moving a file to the macOS bin, never deleting it.

A plain move into ~/.Trash: Finder shows it in the bin and it can be dragged
back, though "Put Back" does not know where it came from. A name already in
the bin gets a timestamp, so nothing in the bin is replaced.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


class TrashError(Exception):
    """The bin is missing or the move failed. The file is where it was."""


def move_to_trash(path: Path, trash_dir: Path) -> Path:
    """Move `path` into `trash_dir`. Returns where it landed."""
    if not trash_dir.is_dir():
        raise TrashError(f"No bin at {trash_dir}; {path.name} was left where it is.")
    target = trash_dir / path.name
    if target.exists():
        target = trash_dir / f"{path.stem} {datetime.now():%Y%m%d-%H%M%S}{path.suffix}"
    try:
        shutil.move(str(path), str(target))
    except OSError as exc:
        raise TrashError(f"Could not move {path.name} to the bin: {exc}") from exc
    return target
