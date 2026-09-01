"""Turning what Alan types into a file on disk.

Two frictions, both from the drop folder. zsh does not expand `~` inside
quotes, and the saved ads are named things like

    Engineering Manager (L5_L6) (Money Flows) _ Ebury _ LinkedIn.pdf

which has spaces and parentheses, so it must be quoted or escaped every time.
So `--file` also accepts a fragment of a name — `--file ebury` — matched
against the drop folder, and `--latest` takes the one just saved.
"""

from __future__ import annotations

from pathlib import Path

# What counts as a saved ad. Everything else in the drop folder — the README,
# outcomes.yaml, .DS_Store — is furniture and must not be matchable.
AD_SUFFIXES = frozenset({".pdf", ".mhtml", ".txt"})


class AdNotFound(Exception):
    """No single saved ad matched what was typed."""


def expand(path: Path | None) -> Path | None:
    """Expand a leading `~` in a path. Used as a typer option callback."""
    return None if path is None else path.expanduser()


def ads_in(jd_dir: Path) -> list[Path]:
    """Every saved ad in the drop folder, newest first."""
    if not jd_dir.is_dir():
        return []
    ads = [
        path
        for path in jd_dir.iterdir()
        if path.is_file() and path.suffix.lower() in AD_SUFFIXES
    ]
    return sorted(ads, key=lambda path: path.stat().st_mtime, reverse=True)


def latest_ad(jd_dir: Path) -> Path:
    """The most recently saved ad — the one just printed to PDF."""
    ads = ads_in(jd_dir)
    if not ads:
        raise AdNotFound(f"No saved ad in {jd_dir}.")
    return ads[0]


def resolve_ad(value: Path, jd_dir: Path) -> Path:
    """Resolve `--file` to a real path.

    An existing path always wins, so nothing that worked before changes.
    Otherwise the value is treated as a fragment of a filename in the drop
    folder, matched case-insensitively. Ambiguity is an error, never a guess:
    ingesting the wrong ad is silent and expensive to notice.
    """
    value = value.expanduser()
    if value.exists():
        return value

    fragment = str(value).casefold()
    matches = [path for path in ads_in(jd_dir) if fragment in path.name.casefold()]

    if len(matches) == 1:
        return matches[0]

    if not matches:
        raise AdNotFound(
            f"No file at {value}, and nothing in {jd_dir} matches {str(value)!r}."
        )

    listed = "\n".join(f"  {path.name}" for path in matches)
    raise AdNotFound(
        f"{len(matches)} ads in {jd_dir} match {str(value)!r}:\n{listed}\n"
        "Use a longer fragment."
    )
