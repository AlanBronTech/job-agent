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