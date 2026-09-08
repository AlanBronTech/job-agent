"""Reading ``runs.jsonl`` back and saying where the money went.

The log records one line per model call. It answered "how much on scoring"
and nothing else — not what one application cost end to end, and not whether a
month's spend was real work or eval runs. Both are now recorded per call, and
this reads them back.

Three things this deliberately does:

* **Names the models it read.** Prices differ by a factor of five, so a total
  over a mixed set of models is not comparable with a total over one. The same
  rule `eval diff` had to learn: anything reading a run history says what it
  read.
* **Counts unpriced calls separately.** A model absent from ``prices.yaml``
  logs ``price_unknown`` and contributes nothing to the total. Reporting the
  total without the count would show a number that quietly excludes real spend.
* **Resolves attribution.** `jd add` parses an ad before the JD has an id, so
  those calls carry a ``run_id`` and the command appends an attribution record
  once the store assigns one. Without the join, the parse — the second largest
  line in the log — has no JD.

Nothing here formats output or touches the store; the CLI adds JD titles.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class SpendError(Exception):
    """The run log is missing or unreadable."""


@dataclass(frozen=True)
class SpendGroup:
    """One row of a breakdown."""

    key: str
    calls: int
    cost_usd: float
    unpriced_calls: int


@dataclass(frozen=True)
class SpendReport:
    calls: int
    total_usd: float
    # The same calls costed again from their token counts at today's prices.
    # None when no price lookup was supplied. A gap between this and
    # `total_usd` means the log was written under a different price table —
    # which is not hypothetical: the hardcoded table priced Sonnet 5 at Sonnet
    # 4.6's rate, so every record before 2026-09-08 overstates by about a third.
    repriced_usd: float | None
    unpriced_calls: int
    models: tuple[str, ...]
    first_ts: float | None
    last_ts: float | None
    by_jd: tuple[SpendGroup, ...]
    by_label: tuple[SpendGroup, ...]
    by_command: tuple[SpendGroup, ...]
    by_source: tuple[SpendGroup, ...]

    @property
    def repricing_gap(self) -> float | None:
        """How far the logged total is from today's prices, as a fraction.

        None when there is nothing to compare. The report shows it rather than
        choosing a number: which total is right depends on whether the price
        changed or the table was wrong, and the log cannot tell.
        """
        if self.repriced_usd is None or not self.total_usd:
            return None
        return (self.total_usd - self.repriced_usd) / self.total_usd

    @property
    def mixed_models(self) -> bool:
        """True when the total spans more than one model.

        Not an error — a year of real use is mixed by definition — but a total
        that spans a 5x price difference needs saying so beside it.
        """
        return len(self.models) > 1


def load_runs(path: Path) -> list[dict]:
    """Every record in the run log, oldest first.

    A malformed line is skipped rather than fatal. The log is appended to from
    inside an ``except OSError: pass``, so a half-written final line is a
    normal thing to find after a crash, and losing one call's cost is a better
    outcome than refusing to report at all.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SpendError(f"No run log at {path}. Nothing has been spent yet.") from exc
    except OSError as exc:
        raise SpendError(f"Could not read {path}: {exc}") from exc

    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def build_report(
    records: list[dict],
    *,
    model: str | None = None,
    source: str | None = None,
    jd_id: int | None = None,
    since: float | None = None,
    price_lookup: "Callable[[str], tuple[float, float] | None] | None" = None,
) -> SpendReport:
    """Aggregate call records into one report, after applying the filters.

    ``price_lookup`` is injected rather than imported: pricing is an adapter
    concern, and `core/` stays callable without one.
    """
    attribution = _attribution(records)
    calls = [r for r in records if r.get("type") != "attribution"]
    calls = [dict(r, jd_id=_jd_of(r, attribution)) for r in calls]

    if model is not None:
        calls = [r for r in calls if model in str(r.get("model") or "")]
    if source is not None:
        calls = [r for r in calls if _source_of(r) == source]
    if jd_id is not None:
        calls = [r for r in calls if r.get("jd_id") == jd_id]
    if since is not None:
        calls = [r for r in calls if (r.get("ts") or 0) >= since]

    timestamps = [r["ts"] for r in calls if isinstance(r.get("ts"), (int, float))]

    return SpendReport(
        calls=len(calls),
        total_usd=sum(r.get("cost_usd") or 0.0 for r in calls),
        repriced_usd=_reprice(calls, price_lookup),
        unpriced_calls=sum(1 for r in calls if _is_unpriced(r)),
        models=tuple(sorted({str(r.get("model")) for r in calls if r.get("model")})),
        first_ts=min(timestamps, default=None),
        last_ts=max(timestamps, default=None),
        by_jd=_group(calls, lambda r: _jd_key(r.get("jd_id"))),
        by_label=_group(calls, lambda r: str(r.get("label") or "(unlabelled)")),
        by_command=_group(calls, lambda r: str(r.get("command") or "(unrecorded)")),
        by_source=_group(calls, _source_of),
    )


def _reprice(calls: list[dict], price_lookup) -> float | None:
    """Cost the same calls again from their token counts at today's prices."""
    if price_lookup is None:
        return None
    total = 0.0
    for record in calls:
        prices = price_lookup(str(record.get("model") or ""))
        if prices is None:
            continue
        in_price, out_price = prices
        total += (
            (record.get("input_tokens") or 0) * in_price
            + (record.get("output_tokens") or 0) * out_price
        ) / 1_000_000
    return total


def _attribution(records: list[dict]) -> dict[str, int]:
    """``run_id`` -> ``jd_id``, from the attribution records."""
    found: dict[str, int] = {}
    for record in records:
        if record.get("type") != "attribution":
            continue
        run_id, jd_id = record.get("run_id"), record.get("jd_id")
        if isinstance(run_id, str) and isinstance(jd_id, int):
            found[run_id] = jd_id
    return found


def _jd_of(record: dict, attribution: dict[str, int]) -> int | None:
    """The JD a call belongs to: recorded directly, or joined on ``run_id``."""
    jd_id = record.get("jd_id")
    if isinstance(jd_id, int):
        return jd_id
    return attribution.get(str(record.get("run_id")))


def _source_of(record: dict) -> str:
    """Records written before `source` existed are real work, not eval runs.

    `eval run` is newer than the log, and the alternative — calling them
    "unknown" — would put most of the history in a bucket that means nothing.
    """
    return str(record.get("source") or "cli")


def _is_unpriced(record: dict) -> bool:
    """True when the call cost something the log could not price.

    `price_unknown` is authoritative where present. Older records predate the
    field, and a null cost in one of those means the same thing.
    """
    if "price_unknown" in record:
        return bool(record["price_unknown"])
    return record.get("cost_usd") is None


def _jd_key(jd_id: object) -> str:
    return f"JD {jd_id}" if isinstance(jd_id, int) else "(no JD)"


def _group(calls: list[dict], key) -> tuple[SpendGroup, ...]:
    """Group calls by ``key``, most expensive first."""
    buckets: dict[str, list[dict]] = {}
    for record in calls:
        buckets.setdefault(key(record), []).append(record)

    groups = [
        SpendGroup(
            key=name,
            calls=len(rows),
            cost_usd=sum(r.get("cost_usd") or 0.0 for r in rows),
            unpriced_calls=sum(1 for r in rows if _is_unpriced(r)),
        )
        for name, rows in buckets.items()
    ]
    return tuple(sorted(groups, key=lambda g: (-g.cost_usd, g.key)))
