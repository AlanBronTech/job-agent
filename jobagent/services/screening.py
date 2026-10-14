"""The first-pass screen, for both front ends: screen ads, store the answer.

Spends about half a cent an ad on the triage route (Haiku by default; see
adapters/llm.py:CHEAP_DEFAULTS). A stored screen is reused unless `force`,
so screening a batch twice costs once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from jobagent.adapters.llm import CallType, LLMError, RunContext, get_client
from jobagent.core import store
from jobagent.core.profile import ProfileError, load_profile
from jobagent.core.screen import ScreenError, screen
from jobagent.services.refusals import NoModel, ProfileInvalid, ProfileMissing
from jobagent.services.workspace import Workspace


@dataclass
class Screened:
    jd_id: int
    title: str
    company: str | None
    decision: str | None  # "score" | "skip" | None on failure
    reason: str
    reused: bool = False


def screen_ads(
    ws: Workspace,
    config,
    jd_ids: list[int],
    *,
    force: bool = False,
    source: str = "cli",
    client_factory: Callable[[RunContext], object] | None = None,
) -> list[Screened]:
    if ws.profile_dir is None:
        raise ProfileMissing()
    try:
        profile = load_profile(ws.profile_dir)
    except ProfileError as exc:
        raise ProfileInvalid(str(exc)) from exc

    out: list[Screened] = []
    for jd_id in jd_ids:
        with store.open_store(ws.db_path) as conn:
            jd = store.get_jd(conn, jd_id)
            stored = store.get_screen(conn, jd_id) if jd else None
        if jd is None:
            out.append(Screened(jd_id, "", None, None, "No such ad."))
            continue
        if stored and not force:
            out.append(Screened(jd_id, jd.title, jd.company, stored["decision"],
                                stored["reason"], reused=True))
            continue
        ctx = RunContext(command="screen", jd_id=jd_id, source=source)
        try:
            client = (client_factory or (lambda c: get_client(CallType.triage, config, c)))(ctx)
        except LLMError as exc:
            raise NoModel(str(exc)) from exc
        try:
            result = screen(jd, profile, client=client)
        except ScreenError as exc:
            out.append(Screened(jd_id, jd.title, jd.company, None, str(exc)))
            continue
        with store.open_store(ws.db_path) as conn:
            store.set_screen(conn, jd_id, decision=result.decision, reason=result.reason,
                             model=getattr(client, "model", "unknown"),
                             at=datetime.now(timezone.utc))
        out.append(Screened(jd_id, jd.title, jd.company, result.decision, result.reason))
    return out
