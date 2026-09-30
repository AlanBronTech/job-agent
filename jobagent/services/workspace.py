"""Whose data a workflow runs against.

Every service takes one of these instead of reading `get_config()`. Locally
there is exactly one, built from `.env` the way the CLI always has; a hosted
version would build one per signed-in person and pass a different document
store. Model routing and API keys are not in here: whoever runs the process
pays for the model calls, hosted or not (specs/001-local-ui, research R11).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jobagent.adapters.document_store import DocumentStore, LocalFolderStore


@dataclass(frozen=True)
class Workspace:
    owner: str
    profile_dir: Path | None
    db_path: Path
    runs_log_path: Path
    jd_dir: Path
    documents: DocumentStore

    @classmethod
    def from_config(cls, config) -> Workspace:
        """The single local workspace. Called by the CLI and the web app, never by services."""
        return cls(
            owner="local",
            profile_dir=config.profile_dir,
            db_path=config.db_path,
            runs_log_path=config.runs_log_path,
            jd_dir=config.jd_dir,
            documents=LocalFolderStore(config.output_dir),
        )
