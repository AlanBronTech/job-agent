"""Workspace.from_config carries exactly the configured locations."""

from __future__ import annotations

import dataclasses

import pytest

from jobagent.adapters.document_store import LocalFolderStore
from jobagent.config import Config
from jobagent.services.workspace import Workspace


def test_from_config(tmp_path):
    config = Config(
        _env_file=None,
        profile_dir=tmp_path / "profile",
        db_path=tmp_path / "db.sqlite",
        runs_log_path=tmp_path / "runs.jsonl",
        jd_dir=tmp_path / "jds",
        output_dir=tmp_path / "out",
    )
    ws = Workspace.from_config(config)
    assert ws.owner == "local"
    assert ws.profile_dir == tmp_path / "profile"
    assert ws.db_path == tmp_path / "db.sqlite"
    assert ws.runs_log_path == tmp_path / "runs.jsonl"
    assert ws.jd_dir == tmp_path / "jds"
    assert isinstance(ws.documents, LocalFolderStore)
    assert ws.documents.output_dir == tmp_path / "out"


def test_is_immutable(tmp_path):
    ws = Workspace.from_config(Config(_env_file=None, db_path=tmp_path / "db"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        ws.owner = "someone else"
