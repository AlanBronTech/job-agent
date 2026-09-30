"""Background runs: an action keeps going when its page closes (FR-016a).

A small thread pool in the server process, with every run recorded in
`services.runs`. Threads rather than asyncio because the model adapter is
synchronous and streams on a blocking socket, so it would need threads anyway;
two workers so a two-minute prep does not hold up scoring a different ad.

The work itself is a callable the route builds around a service call. It
returns a JSON-able summary of what happened, which is stored as the run's
result. The runner knows nothing about what the work is.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from jobagent.services import runs
from jobagent.services.refusals import Refusal
from jobagent.services.workspace import Workspace

Work = Callable[[], dict]


class RunFailed(Exception):
    """Raised by work that has already put its failure into words.

    Recorded as the error verbatim, without an exception type in front: a
    generate that failed on the letter says which files it wrote before it
    stopped, and that sentence is the whole message.
    """


class Runner:
    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="jobagent-run")

    def start(
        self,
        ws: Workspace,
        *,
        kind: str,
        jd_id: int | None,
        run_id: str,
        request: dict,
        work: Work,
    ) -> int:
        """Record the run, then do the work off the request thread. Returns the run id.

        Raises RunInProgress, before any work, if the ad already has one going.
        """
        run = runs.start_run(ws, kind=kind, jd_id=jd_id, run_id=run_id, request=request)
        self._submit(ws, run, work)
        return run

    def _submit(self, ws: Workspace, run: int, work: Work) -> None:
        self._pool.submit(execute, ws, run, work)

    def active(self, ws: Workspace) -> list[runs.Run]:
        """Runs still going, for the Ctrl-C warning."""
        return runs.running(ws)

    def wait(self) -> None:
        """Block until work already started has finished. Nothing new starts."""
        self._pool.shutdown(wait=True, cancel_futures=True)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class SyncRunner(Runner):
    """Does the work inline. For tests: the page after a POST already shows the outcome."""

    def __init__(self) -> None:
        super().__init__(max_workers=1)

    def _submit(self, ws: Workspace, run: int, work: Work) -> None:
        execute(ws, run, work)


def execute(ws: Workspace, run: int, work: Work) -> None:
    """Run the work and record how it ended. Never raises: a worker thread has no caller."""
    try:
        result = work()
    except (Refusal, RunFailed) as exc:
        runs.finish_run(ws, run, status="failed", error=_sentence(exc))
    except Exception as exc:  # the run must end recorded, whatever went wrong
        traceback.print_exc()
        runs.finish_run(ws, run, status="failed", error=f"{type(exc).__name__}: {exc}")
    else:
        runs.finish_run(
            ws, run, status="succeeded", result=result, jd_id=result.get("jd_id")
        )


def _sentence(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    return text[:1].upper() + text[1:] + ("" if text.endswith(".") else ".")

