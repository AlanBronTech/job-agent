"""Shared test fixtures.

Tests run exclusively against ``profile.example/`` — the anonymised, committed
copy of the schema. The real profile lives outside the repo at $PROFILE_DIR and
is never read here.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "profile.example"


@pytest.fixture(autouse=True)
def no_api_keys(monkeypatch):
    """No test reaches a provider, even one a new code path forgot to fake.

    The SDKs read their keys from the environment when none is passed, so a
    shell with a real key exported would otherwise turn a missed fake into a
    billed call.
    """
    for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_libreoffice(monkeypatch):
    """No test renders through LibreOffice: slow, and absent in most places.

    A test that wants a page count patches `count_pages` where it is used.
    """
    from jobagent.adapters import pages

    monkeypatch.setattr(pages, "soffice", lambda: None)


@pytest.fixture(autouse=True)
def no_caffeinate(monkeypatch):
    """No test holds the Mac awake: every faked model call would spawn one."""
    from jobagent.adapters import desktop

    monkeypatch.setattr(desktop, "_caffeinate", lambda: None)


@pytest.fixture(autouse=True)
def no_real_run_log(monkeypatch, tmp_path_factory):
    """No test writes to the real runs.jsonl.

    A Config built without RUNS_LOG_PATH defaults to the repository's own log,
    and tests with faked calls had been appending thousands of 1-token records
    to it since mid-October, inflating `jobagent spend` call counts.
    """
    monkeypatch.setenv("RUNS_LOG_PATH", str(tmp_path_factory.mktemp("runs") / "runs.jsonl"))


@pytest.fixture
def example_dir() -> Path:
    return EXAMPLE_DIR


@pytest.fixture
def profile_factory(tmp_path: Path) -> Callable[..., Path]:
    """Return a factory that materialises a copy of profile.example in a temp
    directory, optionally mutating one file before returning the path.

    ``mutate`` receives the temp profile directory and may edit any file.
    """

    def _make(mutate: Callable[[Path], None] | None = None) -> Path:
        dst = tmp_path / "profile"
        shutil.copytree(EXAMPLE_DIR, dst)
        if mutate is not None:
            mutate(dst)
        return dst

    return _make


def edit_yaml(path: Path, change: Callable[[dict], None]) -> None:
    """Load a YAML file, apply ``change`` to the parsed dict, write it back."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")