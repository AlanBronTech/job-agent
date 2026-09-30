"""Opening a generated document on the Mac the tool runs on.

The UI's server and the person using it are on the same machine — the server
only listens on 127.0.0.1 — so the server running `open` *is* opening the file
for Alan. Review happens in Word, on the real file, because that is what gets
sent; an in-page preview would be a second renderer that could disagree with it.

Both functions refuse any path outside `root`. The web routes only ever pass a
path they built from a folder and file name they listed themselves, but this is
the last line: a forged request can at worst open one of Alan's own documents.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

Runner = Callable[..., object]


def open_file(path: Path, *, root: Path, run: Runner = subprocess.run) -> None:
    """Open a document in its default application (Word, for a .docx)."""
    run(["open", str(_inside(path, root))], check=True)


def reveal(path: Path, *, root: Path, run: Runner = subprocess.run) -> None:
    """Show a file or folder selected in Finder."""
    run(["open", "-R", str(_inside(path, root))], check=True)


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"{path} is outside {root}.")
    if not resolved.exists():
        raise FileNotFoundError(path)
    return resolved
