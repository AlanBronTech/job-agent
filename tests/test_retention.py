"""Saved ads leave the drop folder once JobAgent no longer needs them. Invented data."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
from typer.testing import CliRunner

from jobagent.cli.main import app
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.models import ApplicationStatus
from jobagent.services import pipeline, retention
from jobagent.services.workspace import Workspace
from tests.ui_seed import T0, jd, workspace

runner = CliRunner()


@pytest.fixture
def ws(tmp_path):
    base = workspace(tmp_path)
    (tmp_path / "bin").mkdir()
    base.jd_dir.mkdir()
    return Workspace(**{**base.__dict__, "trash_dir": tmp_path / "bin"})


def saved(ws, name, *, day=0, status=None, age_days=None):
    """A file in the drop folder; with `day`, an ad added from it on T0 + day."""
    path = ws.jd_dir / name
    path.write_text("An invented ad.")
    if age_days is not None:
        stamp = (T0 - timedelta(days=age_days)).timestamp()
        os.utime(path, (stamp, stamp))
        return path, None
    with store.open_store(ws.db_path) as conn:
        jd_id = store.add_jd(conn, jd("Engineering Manager", "Fabrikam", day, source_file=name))
    if status is not None:
        pipeline.save(ws, jd_id, status=status)
    return path, jd_id


def test_closed_unsuccessfully_is_binned(ws):
    path, _ = saved(ws, "a.pdf", status=ApplicationStatus.rejected_screen)
    result = retention.sweep(ws, T0 + timedelta(days=2))
    assert [b.name for b in result.binned] == ["a.pdf"]
    assert not path.exists()
    assert (ws.trash_dir / "a.pdf").exists()


@pytest.mark.parametrize("status", sorted(retention.UNSUCCESSFUL, key=lambda s: s.value))
def test_every_unsuccessful_status_bins_at_once(ws, status):
    path, jd_id = saved(ws, "a.pdf", status=status)
    assert [b.name for b in retention.bin_closed(ws, jd_id).binned] == ["a.pdf"]
    assert not path.exists()


def test_live_application_is_kept_until_30_days(ws):
    path, _ = saved(ws, "a.pdf", status=ApplicationStatus.interview_1)
    assert retention.sweep(ws, T0 + timedelta(days=29)).binned == []
    assert path.exists()
    result = retention.sweep(ws, T0 + timedelta(days=31))
    assert [b.name for b in result.binned] == ["a.pdf"]
    assert not path.exists()


def test_bin_closed_leaves_a_live_application(ws):
    path, jd_id = saved(ws, "a.pdf", status=ApplicationStatus.applied)
    assert retention.bin_closed(ws, jd_id).binned == []
    assert path.exists()


def test_never_added_old_file_is_listed_not_binned(ws):
    path, _ = saved(ws, "orphan.pdf", age_days=40)
    result = retention.sweep(ws, T0)
    assert result.binned == []
    assert result.not_added == ["orphan.pdf"]
    assert path.exists()


def test_dry_run_moves_nothing(ws):
    path, _ = saved(ws, "a.pdf", status=ApplicationStatus.not_applied)
    result = retention.sweep(ws, T0, dry_run=True)
    assert [b.name for b in result.binned] == ["a.pdf"]
    assert path.exists()


def test_no_bin_configured_moves_nothing(ws):
    bare = Workspace(**{**ws.__dict__, "trash_dir": None})
    path, jd_id = saved(bare, "a.pdf", status=ApplicationStatus.not_applied)
    assert retention.sweep(bare, T0 + timedelta(days=60)).binned == []
    assert retention.bin_closed(bare, jd_id).binned == []
    assert path.exists()


def test_name_already_in_the_bin_is_not_replaced(ws):
    (ws.trash_dir / "a.pdf").write_text("something else")
    saved(ws, "a.pdf", status=ApplicationStatus.not_applied)
    retention.sweep(ws, T0)
    assert (ws.trash_dir / "a.pdf").read_text() == "something else"
    assert len(list(ws.trash_dir.iterdir())) == 2


def test_missing_bin_is_reported_and_the_file_kept(ws):
    gone = Workspace(**{**ws.__dict__, "trash_dir": ws.trash_dir / "nope"})
    path, _ = saved(gone, "a.pdf", status=ApplicationStatus.not_applied)
    result = retention.sweep(gone, T0)
    assert result.binned == [] and result.failed[0][0] == "a.pdf"
    assert path.exists()


def test_output_dir_is_never_touched(ws, tmp_path):
    out = tmp_path / "out" / "2026-09_Fabrikam_EngineeringManager"
    out.mkdir(parents=True)
    (out / "resume.docx").write_text("x")
    saved(ws, "a.pdf", status=ApplicationStatus.not_applied)
    retention.sweep(ws, T0 + timedelta(days=90))
    assert (out / "resume.docx").exists()


def test_cli_outcome_bins_and_says_so(ws, tmp_path, monkeypatch):
    config = Config(_env_file=None, db_path=ws.db_path, jd_dir=ws.jd_dir,
                    output_dir=tmp_path / "out", trash_dir=ws.trash_dir)
    monkeypatch.setattr("jobagent.cli.apply.get_config", lambda: config)
    path, jd_id = saved(ws, "a.pdf")
    result = runner.invoke(app, ["outcome", str(jd_id), "rejected_screen", "--worth", "no"])
    assert result.exit_code == 0, result.output
    assert "Moved saved ad to the bin" in result.output
    assert not path.exists()
