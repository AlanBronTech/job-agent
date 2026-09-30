"""The desktop opener: the right command, and nothing outside the output folder."""

from __future__ import annotations

import pytest

from jobagent.adapters import desktop


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, args, check):
        self.calls.append(args)


@pytest.fixture
def root(tmp_path):
    out = tmp_path / "out"
    (out / "2026-09_Acme_EM").mkdir(parents=True)
    (out / "2026-09_Acme_EM" / "resume.docx").write_bytes(b"x")
    return out


def test_open_file_runs_open(root):
    run = FakeRun()
    desktop.open_file(root / "2026-09_Acme_EM" / "resume.docx", root=root, run=run)
    assert run.calls == [["open", str((root / "2026-09_Acme_EM" / "resume.docx").resolve())]]


def test_reveal_runs_open_r(root):
    run = FakeRun()
    desktop.reveal(root / "2026-09_Acme_EM", root=root, run=run)
    assert run.calls == [["open", "-R", str((root / "2026-09_Acme_EM").resolve())]]


def test_path_outside_root_is_refused(root, tmp_path):
    secret = tmp_path / "elsewhere.txt"
    secret.write_text("not a document")
    run = FakeRun()
    with pytest.raises(ValueError):
        desktop.open_file(secret, root=root, run=run)
    with pytest.raises(ValueError):
        desktop.open_file(root / ".." / "elsewhere.txt", root=root, run=run)
    assert run.calls == []


def test_symlink_escaping_root_is_refused(root, tmp_path):
    secret = tmp_path / "elsewhere.txt"
    secret.write_text("not a document")
    (root / "2026-09_Acme_EM" / "link.docx").symlink_to(secret)
    run = FakeRun()
    with pytest.raises(ValueError):
        desktop.open_file(root / "2026-09_Acme_EM" / "link.docx", root=root, run=run)
    assert run.calls == []


def test_missing_file_is_refused(root):
    run = FakeRun()
    with pytest.raises(FileNotFoundError):
        desktop.open_file(root / "2026-09_Acme_EM" / "gone.docx", root=root, run=run)
    assert run.calls == []
