"""services.documents: every refusal before a client exists; what a run writes.

The model is never reached: `get_client` fails the test if it is called where
it should not be, and the builders are replaced by fakes where a run must
complete.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobagent.adapters.llm import RunContext
from jobagent.config import Config
from jobagent.core import store
from jobagent.core.generate import UnusedEntry
from jobagent.core.models import Verdict
from jobagent.core.validation import Severity, ValidationIssue
from jobagent.services import documents
from jobagent.services.documents import GenerationFailed
from jobagent.services.refusals import (
    AlreadyGenerated,
    NoModel,
    NoSuchAd,
    NothingSelected,
    NotScored,
    ProfileMissing,
    SupersedeFailed,
    VerdictIsSkip,
)
from jobagent.services.workspace import Workspace
from tests.ui_seed import TODAY, seed, workspace

EXAMPLE_PROFILE = Path(__file__).resolve().parents[1] / "profile.example"
NOW = datetime(2026, 9, 29, 14, 0, 0)
CONFIG = Config(_env_file=None, llm_default="anthropic:claude-sonnet-5")


@pytest.fixture
def ws(tmp_path):
    base = workspace(tmp_path)
    return Workspace(**{**base.__dict__, "profile_dir": EXAMPLE_PROFILE})


@pytest.fixture
def ids(ws):
    return seed(ws)


@pytest.fixture
def no_client(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a client was built before every refusal had passed")
    monkeypatch.setattr(documents, "get_client", refuse)


@pytest.fixture
def fake_model(monkeypatch):
    """Builders that return canned output and record that they ran."""
    calls = []
    unused = [
        UnusedEntry(id="venture", group="founder", label="An ongoing venture", strong=True, highlight_only=True),
        UnusedEntry(id="role_b", group="roles", label="An older role", strong=False, highlight_only=False),
    ]
    issue = ValidationIssue(rule="banned_phrase", severity=Severity.warning, detail="Invented.")

    def build_resume(jd, profile, assessment, *, client, today, **_):
        calls.append("resume")
        return SimpleNamespace(content="resume content", issues=[issue], unused=unused)

    def build_cover_letter(jd, profile, assessment, *, client, **_):
        calls.append("cover")
        return SimpleNamespace(text="First paragraph.\n\nSecond paragraph.", issues=[])

    def write_resume(content, path):
        path.write_bytes(b"docx:" + content.encode())
        return path

    def write_cover_letter(content, path):
        path.write_bytes(b"docx:" + "|".join(content.paragraphs).encode())
        return path

    monkeypatch.setattr(documents, "get_client", lambda *a, **k: object())
    monkeypatch.setattr(documents.role_kind, "ensure", lambda *a, **k: None)
    monkeypatch.setattr(documents, "build_resume", build_resume)
    monkeypatch.setattr(documents, "build_cover_letter", build_cover_letter)
    monkeypatch.setattr(documents, "write_resume", write_resume)
    monkeypatch.setattr(documents, "write_cover_letter", write_cover_letter)
    return SimpleNamespace(calls=calls, unused=unused)


def run(ws, jd_id, **kw):
    options = dict(resume=True, cover=False, questions=[], today=TODAY, now=NOW)
    options.update(kw)
    return documents.generate(ws, CONFIG, RunContext(command="generate", jd_id=jd_id, source="ui"), jd_id, **options)


# -- refusals, all before a client -------------------------------------------


def test_nothing_selected(ws, ids, no_client):
    with pytest.raises(NothingSelected):
        run(ws, ids["acme"], resume=False)


def test_no_such_ad(ws, ids, no_client):
    with pytest.raises(NoSuchAd):
        run(ws, 999)


def test_not_scored(ws, ids, no_client):
    with pytest.raises(NotScored):
        run(ws, ids["contoso"])


def test_skip_without_overrule(ws, ids, no_client):
    with pytest.raises(VerdictIsSkip) as refused:
        run(ws, ids["northwind"])
    assert refused.value.rationale.startswith("Invented rationale")


def test_overrule_is_recorded_even_when_a_later_gate_refuses(ws, ids, no_client):
    no_profile = Workspace(**{**ws.__dict__, "profile_dir": None})
    with pytest.raises(ProfileMissing):
        run(no_profile, ids["northwind"], overrule=True)
    with store.open_store(ws.db_path) as conn:
        assert store.get_application(conn, ids["northwind"]).overrode_scorer


def test_existing_documents_refuse(ws, ids, no_client):
    plan = documents.plan(ws, ids["acme"], resume=True, cover=False, answers=False, when=TODAY)
    ws.documents.path_for_write(plan.jd, TODAY, plan.names[0]).write_bytes(b"sent")
    with pytest.raises(AlreadyGenerated) as refused:
        run(ws, ids["acme"])
    assert [name for name, _ in refused.value.files] == [plan.names[0]]


def test_no_model(ws, ids, monkeypatch):
    from jobagent.adapters.llm import LLMError

    def unroutable(*a, **k):
        raise LLMError("no route")
    monkeypatch.setattr(documents, "get_client", unroutable)
    with pytest.raises(NoModel):
        run(ws, ids["acme"])


# -- the plan -----------------------------------------------------------------


def test_plan_is_free_and_complete(ws, ids, no_client):
    plan = documents.plan(ws, ids["northwind"], resume=True, cover=True, answers=True, when=TODAY)
    assert plan.verdict is Verdict.skip and plan.needs_overrule
    assert plan.names[-2:] == ["assessment.md", "job-ad.md"] and "answers.md" in plan.names
    assert plan.clashes == []
    assert [e.jd_id for e in plan.history.encounters] == [ids["northwind_old"]]


# -- a run --------------------------------------------------------------------


def test_a_clean_run(ws, ids, fake_model):
    result = run(ws, ids["acme"], cover=True)
    names = [p.name for p in result.written]
    assert names == [
        "AlanBron_Resume_AcmeLogistics_202609.docx",
        "AlanBron_CoverLetter_AcmeLogistics_202609.docx",
        "review.md",
        "assessment.md",
        "job-ad.md",
    ]
    assert fake_model.calls == ["resume", "cover"]
    assert [u.id for u in result.unused] == ["venture", "role_b"]  # order kept: venture first
    assert [i.rule for i in result.issues] == ["banned_phrase"]
    assert result.superseded is None


def test_before_spend_runs_once_after_the_refusals(ws, ids, fake_model):
    seen = []
    run(ws, ids["acme"], before_spend=lambda: seen.append(list(fake_model.calls)))
    assert seen == [[]]


def test_supersede_keeps_the_earlier_folder(ws, ids, fake_model):
    first = run(ws, ids["acme"])
    old_resume = first.written[0]
    old_resume.write_bytes(b"edited by hand and sent")
    second = run(ws, ids["acme"], supersede=True, now=NOW)
    assert second.superseded is not None
    kept = old_resume.parent.parent / second.superseded / old_resume.name
    assert kept.read_bytes() == b"edited by hand and sent"
    assert second.written[0].read_bytes() == b"docx:resume content"


def test_a_failed_move_spends_nothing(ws, ids, fake_model, monkeypatch):
    from jobagent.adapters import docs

    run(ws, ids["acme"])
    fake_model.calls.clear()

    def refuse(*a, **k):
        raise docs.DocsError("permission denied")
    monkeypatch.setattr(docs, "supersede_folder", refuse)
    with pytest.raises(SupersedeFailed):
        run(ws, ids["acme"], supersede=True)
    assert fake_model.calls == []


def test_a_failure_after_spending_names_what_was_written(ws, ids, fake_model, monkeypatch):
    from jobagent.core.generate import GenerateError

    def letter_fails(*a, **k):
        raise GenerateError("the letter timed out")
    monkeypatch.setattr(documents, "build_cover_letter", letter_fails)
    with pytest.raises(GenerationFailed) as failed:
        run(ws, ids["acme"], cover=True)
    assert failed.value.stage == "cover"
    assert [p.name for p in failed.value.written] == ["AlanBron_Resume_AcmeLogistics_202609.docx"]


def test_supersede_and_overwrite_contradict(ws, ids, no_client):
    with pytest.raises(ValueError):
        run(ws, ids["acme"], supersede=True, overwrite=True)


# -- spec 003: the role kind -------------------------------------------------------


def test_the_kind_is_classified_after_the_estimate_and_reaches_every_builder(ws, ids, fake_model, monkeypatch):
    from jobagent.core.models import RoleClassification, RoleKind

    kind = RoleClassification(primary=RoleKind.people_focused, reason="Invented.")
    order, seen = [], []
    monkeypatch.setattr(documents.role_kind, "ensure",
                        lambda *a, **k: order.append("classify") or kind)
    real_resume = documents.build_resume

    def build_resume(*a, kind=None, **k):
        seen.append(kind)
        return real_resume(*a, **k)
    monkeypatch.setattr(documents, "build_resume", build_resume)

    result = run(ws, ids["acme"], before_spend=lambda: order.append("estimate"))
    assert order == ["estimate", "classify"] and seen == [kind]
    assert result.role_kind == kind
    assessment_md = (result.folder / "assessment.md").read_text(encoding="utf-8")
    assert "**Role kind:** people focused — Invented." in assessment_md


def test_a_stored_kind_builds_no_classify_client(ws, ids, fake_model, monkeypatch):
    from jobagent.adapters.llm import CallType
    from jobagent.core.models import RoleClassification, RoleKind

    with store.open_store(ws.db_path) as conn:
        store.set_role_kind(conn, ids["acme"], RoleClassification(primary=RoleKind.technical_lead, reason="x"))
    built = []
    monkeypatch.setattr(documents, "get_client", lambda call_type, *a, **k: built.append(call_type) or object())
    run(ws, ids["acme"])
    assert CallType.classify not in built


def test_a_failed_classification_spends_no_writer_call(ws, ids, fake_model, monkeypatch):
    def fail(*a, **k):
        raise documents.role_kind.RoleKindFailed("unusable")
    monkeypatch.setattr(documents.role_kind, "ensure", fail)
    with pytest.raises(GenerationFailed) as failed:
        run(ws, ids["acme"])
    assert failed.value.stage == "classify" and fake_model.calls == []


def test_the_claim_check_runs_on_the_letter_and_can_be_switched_off(ws, ids, fake_model, monkeypatch):
    from jobagent.core.generate import Sentence
    from jobagent.services import checks

    def letter(*a, **k):
        return SimpleNamespace(text="One.", issues=[], sentences=[Sentence(text="One.", cites=["x.0"])])
    monkeypatch.setattr(documents, "build_cover_letter", letter)
    calls = []
    monkeypatch.setattr(documents.checks, "check_claims",
                        lambda *a, **k: calls.append(1) or checks.NotChecked("timed out"))

    result = run(ws, ids["acme"], cover=True)
    assert calls == [1] and isinstance(result.claims, checks.NotChecked)
    assert any(p.name.startswith("AlanBron_CoverLetter") for p in result.written)

    result = run(ws, ids["acme"], cover=True, overwrite=True, check_claims=False)
    assert calls == [1] and result.claims is None
