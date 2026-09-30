"""Why a workflow declined to run.

Every refusal is raised before any model client is built, so none of them
costs anything. Each carries the facts a caller needs to explain itself and no
wording: the CLI keeps the messages it has always printed, and the UI says the
same thing its own way. A refusal that carried a sentence would make one of
the two front ends quote the other.
"""

from __future__ import annotations

from datetime import datetime


class Refusal(Exception):
    """Base class. Caught by the CLI and the web layer; nothing else raises it."""


class NoSuchAd(Refusal):
    def __init__(self, jd_id: int) -> None:
        super().__init__(f"no job description with id {jd_id}")
        self.jd_id = jd_id


class NotScored(Refusal):
    def __init__(self, jd_id: int) -> None:
        super().__init__(f"JD {jd_id} has not been scored")
        self.jd_id = jd_id


class NothingSelected(Refusal):
    """Generate was asked for no documents."""


class VerdictIsSkip(Refusal):
    """The assessment says skip and the caller has not overruled it."""

    def __init__(self, rationale: str) -> None:
        super().__init__("the assessment says skip")
        self.rationale = rationale


class ThinAd(Refusal):
    """Too little ad text to score, usually a description collapsed at capture."""

    def __init__(self, chars: int) -> None:
        super().__init__(f"only {chars} characters of ad text")
        self.chars = chars


class CaptureTruncated(Refusal):
    """The saved page ends at a '…more' toggle."""


class UnreadableAd(Refusal):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class AdNotFound(Refusal):
    """No single saved ad matched what was asked for."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class AlreadyGenerated(Refusal):
    """This run would replace documents already on disk."""

    def __init__(self, folder: str, files: list[tuple[str, datetime]]) -> None:
        super().__init__(f"{folder} already holds documents for this application")
        self.folder = folder
        self.files = files


class SupersedeFailed(Refusal):
    """The existing folder could not be moved aside; it is untouched."""

    def __init__(self, folder: str, reason: str) -> None:
        super().__init__(f"could not move {folder} aside: {reason}")
        self.folder = folder
        self.reason = reason


class ProfileMissing(Refusal):
    """No profile directory is configured."""


class ProfileInvalid(Refusal):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NoModel(Refusal):
    """No model is routed for this call type, or its key is missing."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class BadDate(Refusal):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class RunInProgress(Refusal):
    """The same ad already has a run going; the caller is pointed at it."""

    def __init__(self, run_id: int) -> None:
        super().__init__(f"run {run_id} is already in progress")
        self.run_id = run_id


class BadUpload(Refusal):
    """A dropped file was refused before anything was written or spent."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail
