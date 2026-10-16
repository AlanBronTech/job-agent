"""Times as Alan reads them: Sydney, whatever the store holds (REVIEW-2026-10-16 D11).

The store keeps UTC so that string order is time order; file times come from
the filesystem in the machine's local time. One page showed both side by
side — "scored 00:18" beside documents written at 11:28 the same morning.
Everything shown goes through `local`.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Australia/Sydney")


def local(moment: datetime) -> datetime:
    """An aware time in Sydney time; a naive one is taken as already local."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(LOCAL_TZ)
