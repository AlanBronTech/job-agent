"""Ads saved into the drop folder: which files count, which one was meant.

Moved from `cli/paths.py` so the UI resolves "the newest saved ad" exactly as
`jd add --latest` does. Two frictions, both from the drop folder: zsh does not
expand `~` inside quotes, and saved ads are named things like

    Engineering Manager (L5_L6) (Platform) _ Acme Logistics _ LinkedIn.pdf

which has spaces and parentheses, so it must be quoted or escaped every time.
So a fragment of a name — `acme` — is matched against the drop folder, and
"latest" takes the one just saved.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jobagent.adapters import mhtml, pdf
from jobagent.adapters.adtext import ExtractedAd
from jobagent.adapters.llm import CallType, LLMError, RunContext, get_client, log_attribution
from jobagent.core import history, store
from jobagent.core.jd import parse_jd
from jobagent.core.models import THIN_AD_CHARS
from jobagent.services.refusals import AdNotFound, CaptureTruncated, NoModel, UnreadableAd
from jobagent.services.results import AddResult
from jobagent.services.workspace import Workspace

# What counts as a saved ad. Everything else in the drop folder — the README,
# outcomes.yaml, .DS_Store — is furniture and must not be matchable.
AD_SUFFIXES = frozenset({".pdf", ".mhtml", ".txt"})


def ads_in(jd_dir: Path) -> list[Path]:
    """Every saved ad in the drop folder, newest first."""
    if not jd_dir.is_dir():
        return []
    ads = [
        path
        for path in jd_dir.iterdir()
        if path.is_file() and path.suffix.lower() in AD_SUFFIXES
    ]
    return sorted(ads, key=lambda path: path.stat().st_mtime, reverse=True)


def latest_ad(jd_dir: Path) -> Path:
    """The most recently saved ad — the one just printed to PDF."""
    ads = ads_in(jd_dir)
    if not ads:
        raise AdNotFound(f"No saved ad in {jd_dir}.")
    return ads[0]


def resolve_ad(value: Path, jd_dir: Path) -> Path:
    """Resolve `--file` to a real path.

    An existing path always wins, so nothing that worked before changes.
    Otherwise the value is treated as a fragment of a filename in the drop
    folder, matched case-insensitively. Ambiguity is an error, never a guess:
    ingesting the wrong ad is silent and expensive to notice.
    """
    value = value.expanduser()
    if value.exists():
        return value

    fragment = str(value).casefold()
    matches = [path for path in ads_in(jd_dir) if fragment in path.name.casefold()]

    if len(matches) == 1:
        return matches[0]

    if not matches:
        raise AdNotFound(
            f"No file at {value}, and nothing in {jd_dir} matches {str(value)!r}."
        )

    listed = "\n".join(f"  {path.name}" for path in matches)
    raise AdNotFound(
        f"{len(matches)} ads in {jd_dir} match {str(value)!r}:\n{listed}\n"
        "Use a longer fragment."
    )


# --------------------------------------------------------------------------- #
# Reading and adding an ad
# --------------------------------------------------------------------------- #


@dataclass
class AdInput:
    """What will be parsed, read without spending anything.

    `page_chars` and `truncated` exist only for a saved page (.mhtml or .pdf):
    the page's text before and after removing platform furniture, and whether
    it ends at a '…more' toggle. Plain text and pasted text have neither.
    """

    raw_text: str
    name: str | None = None
    source_url: str | None = None
    posting_metadata: str | None = None
    page_chars: int | None = None
    truncated: bool = False

    @classmethod
    def from_page(cls, page: ExtractedAd, name: str | None = None) -> AdInput:
        return cls(
            raw_text=page.text,
            name=name,
            source_url=page.source_url,
            posting_metadata=page.posting_metadata,
            page_chars=len(page.full_text),
            truncated=page.truncated,
        )

    @property
    def thin_chars(self) -> int | None:
        """Set when a saved page yielded so little text it is probably collapsed.

        Only for saved pages, as the CLI has always done: a short pasted ad
        can be genuinely short, and `score` refuses a stub anyway.
        """
        if self.page_chars is None or len(self.raw_text) >= THIN_AD_CHARS:
            return None
        return len(self.raw_text)


def extract_saved_page(file: Path) -> ExtractedAd | None:
    """Unwrap a saved job page, or None if this is plain text.

    Neither adapter fetches anything; both read the file Alan already saved.
    """
    if mhtml.looks_like_mhtml(file):
        reader, error = mhtml.extract_ad, mhtml.MHTMLError
    elif pdf.looks_like_pdf(file):
        reader, error = pdf.extract_ad, pdf.PDFError
    else:
        return None
    try:
        return reader(file)
    except error as exc:
        raise UnreadableAd(str(exc)) from exc


def read_ad(*, file: Path | None = None, text: str | None = None) -> AdInput:
    """The text a parse would read. Free. Raises UnreadableAd."""
    if (file is None) == (text is None):
        raise ValueError("give exactly one of file or text")
    if text is not None:
        return AdInput(raw_text=text)
    page = extract_saved_page(file)
    if page is not None:
        return AdInput.from_page(page, file.name)
    try:
        return AdInput(raw_text=file.read_text(encoding="utf-8"), name=file.name)
    except (OSError, UnicodeDecodeError) as exc:
        raise UnreadableAd(f"Could not read {file}: {exc}") from exc


def add(
    ws: Workspace,
    config,
    ctx: RunContext,
    ad: AdInput,
    *,
    source: str | None = None,
    before_spend: Callable[[], None] | None = None,
    client=None,
) -> AddResult:
    """Parse an ad and store it.

    Refuses a truncated capture before any spend: parsing half an ad gives a
    confident, wrong answer. The parse call is logged before the ad has an id,
    so one attribution record links them once it does, for `spend`.
    Raises JDError if the parse fails and StoreError if the save does.
    """
    if ad.truncated:
        raise CaptureTruncated()
    if client is None:
        try:
            client = get_client(CallType.parse_jd, config, ctx)
        except LLMError as exc:
            raise NoModel(str(exc)) from exc

    if before_spend is not None:
        before_spend()
    jd = parse_jd(ad.raw_text, client=client, source=source)
    jd.source_url = ad.source_url
    jd.source_metadata = ad.posting_metadata

    with store.open_store(ws.db_path) as conn:
        jd.id = store.add_jd(conn, jd)
        log_attribution(ws.runs_log_path, client.context.run_id, jd.id)
        seen_before = history.company_history(conn, jd)
    return AddResult(jd=jd, history=seen_before, thin_chars=ad.thin_chars)
