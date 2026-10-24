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


class keep_awake:
    """Hold off idle sleep while a long model call runs, on macOS.

    A resume generate started at 01:53 on 2026-10-25 sat frozen until 06:12:
    the Mac idled into sleep on battery, the streaming connection stalled, and
    the call only timed out once the lid was opened. `caffeinate -i` holds an
    idle-sleep assertion for as long as it runs. Closing the lid still sleeps,
    as it should. Elsewhere, or if caffeinate is missing, this does nothing.
    """

    def __init__(self, spawn: Callable[..., object] = subprocess.Popen) -> None:
        self._spawn = spawn
        self._process = None

    def __enter__(self) -> "keep_awake":
        if _caffeinate():
            try:
                self._process = self._spawn(
                    ["caffeinate", "-i"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except OSError:
                self._process = None
        return self

    def __exit__(self, *exc) -> None:
        if self._process is not None:
            self._process.terminate()
            self._process = None


def _caffeinate() -> str | None:
    import shutil

    return shutil.which("caffeinate")
