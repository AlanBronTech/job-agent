"""Score an ad against the profile: the refusals `score` had, for both front ends.

A stub ad is refused before anything is spent: the scorer reads two sentences
with the same confidence it reads a whole ad, and on JD 23 it assessed five
requirements the ad never stated. `force` overrides that, as `--force` does.
Reading the last assessment back (`score --last`) stays in the CLI and the
listing service; it spends nothing and needs none of this.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from jobagent.adapters.llm import CallType, LLMError, RunContext, get_client
from jobagent.core import history, store
from jobagent.core.profile import ProfileError, load_profile
from jobagent.core.scoring import score_fit
from jobagent.core.store import StoreError
from jobagent.services import reapply
from jobagent.services.refusals import (
    NoModel,
    NoSuchAd,
    PossiblySameJob,
    ProfileInvalid,
    ProfileMissing,
    SameJobRecently,
    ThinAd,
)
from jobagent.services.results import ScoreResult
from jobagent.services.workspace import Workspace


def load(ws: Workspace, jd_id: int):
    """The ad and its company history. Free. Raises NoSuchAd."""
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
        if jd is None:
            raise NoSuchAd(jd_id)
        return jd, history.company_history(conn, jd)


def score(
    ws: Workspace,
    config,
    ctx: RunContext,
    jd_id: int,
    *,
    force: bool = False,
    before_spend: Callable[[], None] | None = None,
    client_factory: Callable[[], object] | None = None,
    today: date | None = None,
) -> ScoreResult:
    """Score and store. Raises ScoringError if the model's answer is unusable.

    A store failure after scoring is a warning in the result, not an error:
    the assessment was paid for and is shown either way.
    """
    jd, seen_before = load(ws, jd_id)
    refuse_if_reapplying(ws, jd_id, today or date.today())

    if jd.thin and not force:
        raise ThinAd(len(jd.raw_text))
    if ws.profile_dir is None:
        raise ProfileMissing()
    try:
        profile = load_profile(ws.profile_dir)
    except ProfileError as exc:
        raise ProfileInvalid(str(exc)) from exc
    try:
        client = (client_factory or (lambda: get_client(CallType.score, config, ctx)))()
    except LLMError as exc:
        raise NoModel(str(exc)) from exc

    if before_spend is not None:
        before_spend()
    assessment = score_fit(jd, profile, client=client)

    warnings = []
    try:
        with store.open_store(ws.db_path) as conn:
            assessment.id = store.add_assessment(conn, assessment)
    except StoreError as exc:
        warnings.append(f"Scored, but could not save. {exc}")
    return ScoreResult(jd=jd, assessment=assessment, history=seen_before, warnings=warnings)


def refuse_if_reapplying(ws: Workspace, jd_id: int, today: date) -> None:
    """The six-month rule, before anything is spent (spec 002, FR-009)."""
    state = reapply.check(ws, jd_id, today)
    if isinstance(state, reapply.SameJob):
        raise SameJobRecently(state.match)
    if isinstance(state, reapply.PossiblySame):
        raise PossiblySameJob(state.match)
