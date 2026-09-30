"""The background runner: one run per ad, failures recorded, work off the request thread."""

from __future__ import annotations

import threading

import pytest

from jobagent.services import runs
from jobagent.services.refusals import NotScored, RunInProgress
from jobagent.web.runner import Runner, SyncRunner
from tests.ui_seed import seed, workspace


@pytest.fixture
def ws(tmp_path):
    return workspace(tmp_path)


@pytest.fixture
def ids(ws):
    return seed(ws)


def test_success_is_recorded_with_its_result(ws, ids):
    run = SyncRunner().start(ws, kind="score", jd_id=ids["acme"], run_id="r1",
                             request={}, work=lambda: {"score": 78})
    got = runs.get_run(ws, run)
    assert got.status == "succeeded" and got.result == {"score": 78}


def test_a_refusal_is_recorded_as_a_sentence(ws, ids):
    def work():
        raise NotScored(ids["contoso"])
    run = SyncRunner().start(ws, kind="generate", jd_id=ids["contoso"], run_id="r1",
                             request={}, work=work)
    got = runs.get_run(ws, run)
    assert got.status == "failed" and got.error == f"JD {ids['contoso']} has not been scored."


def test_an_unexpected_error_is_recorded_not_raised(ws, ids, capsys):
    def work():
        raise TimeoutError("read timed out")
    run = SyncRunner().start(ws, kind="prep", jd_id=ids["acme"], run_id="r1",
                             request={}, work=work)
    got = runs.get_run(ws, run)
    assert got.status == "failed" and got.error == "TimeoutError: read timed out"


def test_add_ad_records_the_ad_it_created(ws, ids):
    run = SyncRunner().start(ws, kind="add_ad", jd_id=None, run_id="r1",
                             request={"input_key": "ad.pdf"}, work=lambda: {"jd_id": ids["contoso"]})
    assert runs.get_run(ws, run).jd_id == ids["contoso"]


def test_work_runs_off_the_request_thread_and_a_second_start_is_refused(ws, ids):
    release = threading.Event()
    started = threading.Event()
    caller = threading.get_ident()
    seen = {}

    def slow():
        seen["thread"] = threading.get_ident()
        started.set()
        release.wait(5)
        return {}

    runner = Runner()
    try:
        first = runner.start(ws, kind="prep", jd_id=ids["acme"], run_id="r1", request={}, work=slow)
        assert started.wait(5)
        assert seen["thread"] != caller
        assert runs.get_run(ws, first).status == "running"
        assert [r.id for r in runner.active(ws)] == [first]
        with pytest.raises(RunInProgress):
            runner.start(ws, kind="score", jd_id=ids["acme"], run_id="r2", request={}, work=dict)
        release.set()
        for _ in range(100):
            if runs.get_run(ws, first).status != "running":
                break
            threading.Event().wait(0.02)
        assert runs.get_run(ws, first).status == "succeeded"
    finally:
        release.set()
        runner.shutdown()


def test_restart_marks_leftovers_interrupted(ws, ids):
    runs.start_run(ws, kind="score", jd_id=ids["acme"], run_id="r1", request={})
    assert runs.interrupt_running(ws) == 1
    assert [r.status for r in runs.unseen_finished(ws)] == ["interrupted"]
