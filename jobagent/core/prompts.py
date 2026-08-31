"""Loading versioned prompts from ``prompts/*.md``.

Prompts are files, not string literals, per CLAUDE.md — they get edited,
diffed and regression-tested independently of the code that calls them.

Placeholders are substituted by literal replacement, not ``str.format``.
Prompt files contain JSON examples full of braces, and ``format`` would choke
on every one of them.
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class PromptError(Exception):
    """A prompt file is missing, empty, or has an unfilled placeholder."""


def load_prompt(name: str, **placeholders: str) -> str:
    """Load ``prompts/<name>.md`` and substitute ``{key}`` for each keyword.

    Raises ``PromptError`` if the file is missing or if a declared placeholder
    is still present after substitution — a silently unfilled ``{jd_text}``
    would otherwise reach the model as literal text.
    """
    path = PROMPTS_DIR / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PromptError(f"No prompt named {name!r} at {path}") from exc
    except OSError as exc:
        raise PromptError(f"Could not read prompt {name!r} at {path}: {exc}") from exc

    if not text.strip():
        raise PromptError(f"Prompt {name!r} at {path} is empty")

    for key, value in placeholders.items():
        text = text.replace(f"{{{key}}}", value)

    for key in placeholders:
        if f"{{{key}}}" in text:  # pragma: no cover - defensive
            raise PromptError(f"Placeholder {{{key}}} still unfilled in {name!r}")

    return text
