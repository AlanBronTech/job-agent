"""Turning what Alan types into a file on disk.

Two frictions, both from the drop folder. zsh does not expand `~` inside
quotes, and the saved ads are named things like

    Engineering Manager (L5_L6) (Platform) _ Acme Logistics _ LinkedIn.pdf

which has spaces and parentheses, so it must be quoted or escaped every time.
So `--file` also accepts a fragment of a name — `--file acme` — matched
against the drop folder, and `--latest` takes the one just saved.
"""

from __future__ import annotations

from pathlib import Path

from jobagent.services.ads import AD_SUFFIXES, ads_in, latest_ad, resolve_ad  # noqa: F401
from jobagent.services.refusals import AdNotFound  # noqa: F401


def expand(path: Path | None) -> Path | None:
    """Expand a leading `~` in a path. Used as a typer option callback."""
    return None if path is None else path.expanduser()
