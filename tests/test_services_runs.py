"""The UI run registry: one run per ad, interrupted on restart, seen once viewed."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from jobagent.core import store
from jobagent.services import runs
from jobagent.services.refusals import RunInProgress
from tests.ui_seed import seed, workspace


@pytest.fixture
def ws(tmp_path):
    return workspace(tmp_path)


@pytest.fixture
def ids(ws):
    return seed(ws)


def test_start_finish_and_read(ws, ids):
    run = runs.start_run(ws, kind="score", jd_id=ids["acme"], run_id="r1", request={})
    got = runs.get_run(ws, run)
    assert (got.status, got.kind, got.jd_id, got.owner) == ("running", "score", ids["acme"], "local")
    runs.finish_run(ws, run, status="succeeded", result={"score": 78})
    got = runs.get_run(ws, run)
    assert got.status == "succeeded" and got.result == {"score": 78} and got.finished_at


def test_second_start_for_the_same_ad_is_refused(ws, ids):
    first = runs.start_run(ws, kind="score", jd_id=ids["acme"], run_id="r1", request={})
    with pytest.raises(RunInProgress) as refused:
        runs.start_run(ws, kind="generate", jd_id=ids["acme"], run_id="r2", request={})
    assert refused.value.run_id == first
    # A different ad is fine.
    runs.start_run(ws, kind="score", jd_id=ids["contoso"], run_id="r3", request={})


def test_concurrent_starts_produce_one_run(ws, ids):
    results = []

    def attempt(n):
        try:
            results.append(runs.start_run(ws, kind="score", jd_id=ids["acme"], run_id=f"r{n}", request={}))
        except RunInProgress:
            results.append(None)

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len([r for r in results if r is not None]) == 1


def test_after_finishing_the_ad_can_run_again(ws, ids):
    run = runs.start_run(ws, kind="score", jd_id=ids["acme"], run_id="r1", request={})
    runs.finish_run(ws, run, status="failed", error="timed out")
    runs.start_run(ws, kind="score", jd_id=ids["acme"], run_id="r2", request={})


def test_identical_paste_twice_is_refused(ws):
    runs.start_run(ws, kind="add_ad", jd_id=None, run_id="r1", request={"input_key": "sha256:abc"})
    with pytest.raises(RunInProgress):
        runs.start_run(ws, kind="add_ad", jd_id=None, run_id="r2", request={"input_key": "sha256:abc"})
    runs.start_run(ws, kind="add_ad", jd_id=None, run_id="r3", request={"input_key": "sha256:def"})


def test_add_ad_records_the_ad_it_created(ws, ids):
    run = runs.start_run(ws, kind="add_ad", jd_id=None, run_id="r1", request={"input_key": "a.pdf"})
    runs.finish_run(ws, run, status="succeeded", jd_id=ids["contoso"])
    assert runs.get_run(ws, run).jd_id == ids["contoso"]


def test_interrupt_running(ws, ids):
    run = runs.start_run(ws, kind="prep", jd_id=ids["acme"], run_id="r1", request={})
    assert runs.interrupt_running(ws) == 1
    assert runs.get_run(ws, run).status == "interrupted"
    assert [r.id for r in runs.unseen_finished(ws)] == [run]


def test_seen(ws, ids):
    a = runs.start_run(ws, kind="score", jd_id=ids["acme"], run_id="r1", request={})
    b = runs.start_run(ws, kind="score", jd_id=ids["contoso"], run_id="r2", request={})
    running = runs.start_run(ws, kind="score", jd_id=ids["fabrikam"], run_id="r3", request={})
    runs.finish_run(ws, a, status="succeeded")
    runs.finish_run(ws, b, status="succeeded")
    assert {r.id for r in runs.unseen_finished(ws)} == {a, b}
    runs.mark_seen(ws, a)
    runs.mark_seen_for_jd(ws, ids["contoso"])
    runs.mark_seen(ws, running)  # still running: not seen yet
    assert runs.unseen_finished(ws) == []
    runs.finish_run(ws, running, status="succeeded")
    assert [r.id for r in runs.unseen_finished(ws)] == [running]


def test_cascade_on_jd_delete(ws, ids):
    run = runs.start_run(ws, kind="score", jd_id=ids["contoso"], run_id="r1", request={})
    runs.finish_run(ws, run, status="succeeded")
    with store.open_store(ws.db_path) as conn:
        store.delete_jd(conn, ids["contoso"])
    assert runs.get_run(ws, run) is None


def test_existing_database_keeps_its_schema_version(ws, ids):
    with store.open_store(ws.db_path) as conn:
        before = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    runs.start_run(ws, kind="score", jd_id=ids["acme"], run_id="r1", request={})
    conn = sqlite3.connect(ws.db_path)
    after = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    assert before == after == str(store.SCHEMA_VERSION)


def test_unknown_kind_is_refused(ws):
    with pytest.raises(ValueError):
        runs.start_run(ws, kind="delete_everything", jd_id=None, run_id="r1", request={})
