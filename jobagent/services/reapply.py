"""The six-month rule, as a decision about one ad.

`check` gathers the history `core.reapply.match` needs and applies Alan's
recorded answers: a "different job" clears a possible match, a "same job"
confirms it, and an overrule waives the rule for that ad only. Called by
scoring and generation before anything is spent.

If the profile cannot be loaded, the check stands aside and returns Clear, so
the existing ProfileMissing / ProfileInvalid refusal fires as it always has
(spec 002, analysis U2). Without the profile there is no window to apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from jobagent.core import reapply as core_reapply
from jobagent.core import store
from jobagent.core.models import ReapplyDecision
from jobagent.core.profile import ProfileError, load_profile
from jobagent.services.refusals import NoSuchAd
from jobagent.services.workspace import Workspace


@dataclass(frozen=True)
class Clear:
    decision: str | None = None  # the recorded decision that cleared it, if any
    kind: str = "clear"


@dataclass(frozen=True)
class SameJob:
    match: core_reapply.Match
    kind: str = "same"


@dataclass(frozen=True)
class PossiblySame:
    match: core_reapply.Match
    kind: str = "possibly_same"


def window_days(ws: Workspace) -> int | None:
    """The profile's window, or None when the rule is off or cannot be read."""
    if ws.profile_dir is None:
        return None
    try:
        return load_profile(ws.profile_dir).assets.target_filters.reapply_window_days
    except ProfileError:
        return None


def check(ws: Workspace, jd_id: int, today: date) -> Clear | SameJob | PossiblySame:
    window = window_days(ws)
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
        if jd is None:
            raise NoSuchAd(jd_id)
        if window is None:
            return Clear()
        decision = store.get_reapply_decision(conn, jd_id)
        if decision is not None and decision.decision == "overrule":
            return Clear("overrule")
        tracked = [
            (other, application)
            for other, application in store.list_jds_with_applications(conn)
            if application is not None
        ]
        outside = store.list_outside(conn)
        scored = []
        for other in store.list_jds(conn):
            if other.id == jd_id or not other.requisition_id:
                continue
            assessment = store.latest_assessment(conn, other.id)
            if assessment is not None:
                scored.append((other, assessment.scored_at.date()))

    found = core_reapply.match(
        jd, tracked=tracked, outside=outside, scored=scored, window_days=window, today=today
    )
    if found is None:
        return Clear()
    if found.kind == "same":
        return SameJob(found)
    if decision is not None and decision.decision == "different":
        return Clear("different")
    if decision is not None and decision.decision == "same":
        return SameJob(found)
    return PossiblySame(found)


def decide(ws: Workspace, jd_id: int, decision: str, matched: str = "") -> None:
    """Record Alan's answer for this ad: "same", "different" or "overrule"."""
    if decision not in {"same", "different", "overrule"}:
        raise ValueError(f"not a reapply decision: {decision!r}")
    with store.open_store(ws.db_path) as conn:
        if store.get_jd(conn, jd_id) is None:
            raise NoSuchAd(jd_id)
        store.set_reapply_decision(
            conn,
            ReapplyDecision(
                jd_id=jd_id,
                decision=decision,
                matched=matched or "unspecified",
                decided_at=datetime.now(timezone.utc),
            ),
        )
