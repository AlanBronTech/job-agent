"""The master resume chosen for an ad, for every place the assessment is shown.

Free: reads the registry and applies `core.masters.select_master`. A broken
registry never stops a score or a page from showing; it comes back as a
choice whose reason says what is wrong, so it is seen where the choice would
have been.
"""

from __future__ import annotations

from jobagent.core.masters import load_masters, select_master
from jobagent.core.models import JobDescription, MasterChoice, RoleClassification
from jobagent.core.profile import ProfileError
from jobagent.services.workspace import Workspace


def choose(
    ws: Workspace, jd: JobDescription, kind: RoleClassification | None
) -> MasterChoice | None:
    """The choice for this ad, or None when there is no profile or no registry."""
    if ws.profile_dir is None:
        return None
    try:
        registry = load_masters(ws.profile_dir)
    except ProfileError as exc:
        return MasterChoice(
            reason=f"No master chosen: the master list is invalid. {exc}"
        )
    return select_master(jd, kind, registry)
