"""The role kind of an ad: classified once, on first need, and stored (spec 003).

A separate small call rather than a field of the parse or the score, so no
prompt the eval set measures changes, and an old ad costs nothing unless it is
worked on again. `ensure` is free when the ad already carries a kind; an
amendment clears it, so a changed ad is classified afresh.
"""

from __future__ import annotations

from collections.abc import Callable

from jobagent.adapters.llm import CallType, LLMError, RunContext, get_client
from jobagent.core import roles, store
from jobagent.core.models import RoleClassification
from jobagent.services.refusals import NoModel, NoSuchAd
from jobagent.services.workspace import Workspace


class RoleKindFailed(Exception):
    """The classifier was called and its answer was unusable. Nothing stored."""


def stored(ws: Workspace, jd_id: int) -> RoleClassification | None:
    """The stored kind, or None. Never spends."""
    with store.open_store(ws.db_path) as conn:
        return store.get_role_kind(conn, jd_id)


def needs_classify(ws: Workspace, jd_id: int) -> bool:
    """Whether `ensure` would make a paid call. For cost estimates."""
    return stored(ws, jd_id) is None


def ensure(
    ws: Workspace,
    config,
    ctx: RunContext,
    jd_id: int,
    *,
    client_factory: Callable[[], object] | None = None,
) -> RoleClassification:
    """The ad's kind: the stored one if any, otherwise classified and stored."""
    with store.open_store(ws.db_path) as conn:
        jd = store.get_jd(conn, jd_id)
        if jd is None:
            raise NoSuchAd(jd_id)
        existing = store.get_role_kind(conn, jd_id)
    if existing is not None:
        return existing

    try:
        client = (client_factory or (lambda: get_client(CallType.classify, config, ctx)))()
    except LLMError as exc:
        raise NoModel(str(exc)) from exc
    try:
        classification = roles.classify(jd, client=client)
    except roles.ClassifyError as exc:
        raise RoleKindFailed(str(exc)) from exc

    with store.open_store(ws.db_path) as conn:
        store.set_role_kind(conn, jd_id, classification)
    return classification
