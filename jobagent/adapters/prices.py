"""Model prices, read from ``prices.yaml`` at runtime.

Prices drift, and a figure that drifts silently is worse than no figure at all:
the table this replaced had Sonnet 5 at Sonnet 4.6's rate, so every cost in
``runs.jsonl`` was overstated by about a third and nothing said so.

Two rules follow from that, and both are enforced here rather than trusted to
whoever edits the file next:

* The prices live in data, with the date they were checked and the pages they
  were checked against. Correcting a price is an edit to a YAML file.
* A model with no entry has no price. ``estimate_cost`` returns ``None`` and the
  model is recorded as unpriced, so the run log carries ``price_unknown`` and
  the command says so on the way out. A missing price must never read as free.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PRICES_FILE = Path(__file__).resolve().parents[2] / "prices.yaml"


class PriceError(Exception):
    """``prices.yaml`` is missing, malformed, or has an unusable entry."""


@dataclass(frozen=True)
class PriceTable:
    """USD per million tokens, keyed by model id prefix."""

    checked_on: str
    models: dict[str, tuple[float, float]]

    def lookup(self, model: str) -> tuple[float, float] | None:
        """Prices for ``model``, or None if the table does not cover it.

        Exact match first, then the longest key the id starts with. The longest
        match is what keeps ``claude-opus-4-1`` — three times the price of the
        rest of the family — from resolving as ``claude-opus-4-8``, and
        ``startswith`` rather than substring matching is what stops a key
        matching in the middle of an unrelated id.
        """
        if model in self.models:
            return self.models[model]
        candidates = [key for key in self.models if model.startswith(key)]
        if not candidates:
            return None
        return self.models[max(candidates, key=len)]


@lru_cache(maxsize=4)
def load_prices(path: Path | None = None) -> PriceTable:
    """Load and validate the price table. Cached — the file does not change
    inside a run."""
    path = path or PRICES_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PriceError(f"No price table at {path}") from exc
    except OSError as exc:
        raise PriceError(f"Could not read {path}: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PriceError(_format_yaml_error(path, exc)) from exc

    if not isinstance(data, dict):
        raise PriceError(f"{path.name}: expected a top-level mapping")

    checked_on = str(data.get("checked_on") or "")
    if not checked_on:
        raise PriceError(
            f"{path.name}: no `checked_on` date. A price table without one "
            "cannot be told from a stale one."
        )

    raw = data.get("models")
    if not isinstance(raw, dict) or not raw:
        raise PriceError(f"{path.name}: `models` must be a non-empty mapping")

    models: dict[str, tuple[float, float]] = {}
    for model, prices in raw.items():
        if not isinstance(prices, dict) or {"input", "output"} - prices.keys():
            raise PriceError(
                f"{path.name}: {model} needs both `input` and `output` prices"
            )
        try:
            models[str(model)] = (float(prices["input"]), float(prices["output"]))
        except (TypeError, ValueError) as exc:
            raise PriceError(
                f"{path.name}: {model} has a non-numeric price: {prices}"
            ) from exc

    return PriceTable(checked_on=checked_on, models=models)


def _format_yaml_error(path: Path, exc: yaml.YAMLError) -> str:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or "invalid YAML"
    if mark is not None:
        # PyYAML marks are 0-indexed; humans count from 1.
        return f"{path.name}:{mark.line + 1}:{mark.column + 1}: {problem}"
    return f"{path.name}: {problem}"


# --------------------------------------------------------------------------- #
# Models seen this run that the table does not cover
#
# Process-wide because a single command can build several clients — `generate`
# writes a resume and a cover letter — and the point is one line at the end of
# the command, not one per call.
# --------------------------------------------------------------------------- #

_unpriced: set[str] = set()


def note_unpriced(model: str) -> None:
    _unpriced.add(model)


def unpriced_models() -> tuple[str, ...]:
    """Models called this run with no entry in the price table."""
    return tuple(sorted(_unpriced))


def clear_unpriced() -> None:
    _unpriced.clear()
