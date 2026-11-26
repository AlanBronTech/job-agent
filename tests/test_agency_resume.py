"""Spec 005: the agency resume, a longer PROFILE written for one ad.

Invented data only (Constitution VI): the example profile's person, and
invented employers and agencies.
"""

from __future__ import annotations

from jobagent.core.generate import SHORT_PROFILE_RULE, profile_rule
from jobagent.core.models import ResumeKind
from jobagent.core.prompts import load_prompt


def test_resume_kinds():
    assert ResumeKind.master.uses_master and not ResumeKind.master.long_profile
    assert ResumeKind.master_profile.uses_master and ResumeKind.master_profile.long_profile
    assert not ResumeKind.custom.uses_master and not ResumeKind.custom.long_profile
    assert ResumeKind.custom_profile.long_profile and not ResumeKind.custom_profile.uses_master
    assert not ResumeKind.master.generated
    assert all(k.generated for k in ResumeKind if k is not ResumeKind.master)


def test_profile_rule_default_is_the_short_rule():
    assert profile_rule(False) == SHORT_PROFILE_RULE
    assert SHORT_PROFILE_RULE.startswith("**PROFILE is two short paragraphs")


def test_profile_rule_long_is_the_shared_agency_rules():
    rule = profile_rule(True)
    assert rule == load_prompt("long_profile_rules").strip()
    assert "at most 250 words" in rule


def test_resume_prompt_has_one_profile_slot():
    text = (load_prompt.__globals__["PROMPTS_DIR"] / "generate_resume.md").read_text()
    assert text.count("{profile_rule}") == 1


# --------------------------------------------------------------------------- #
# T007: a copy of the master with only PROFILE replaced
# --------------------------------------------------------------------------- #

import hashlib
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Pt, RGBColor

from jobagent.adapters.docx_writer import DocxError, replace_profile


def build_master(path: Path, *, profile_heading: str | None = "PROFILE", body: int = 2,
                 twice: bool = False) -> Path:
    """An invented master in the masters' shape: plain paragraphs, run formatting."""
    doc = Document()

    def para(text, *, size=10.5, bold=False, colour=None, style=None):
        p = doc.add_paragraph(style=style)
        run = p.add_run(text)
        run.font.size = Pt(size)
        run.bold = bold
        if colour:
            run.font.color.rgb = colour
        return p

    para("SAM RIVERA", size=26, bold=True)
    para("Engineering Manager  ·  Platform", colour=RGBColor(0x22, 0x58, 0xA5))
    para("Melbourne  ·  sam@example.com", size=9.5)
    for _ in range(2 if twice else 1):
        if profile_heading:
            para(profile_heading, size=11.5, bold=True)
        for n in range(body):
            para(f"Master profile paragraph {n + 1}.", colour=RGBColor(0x10, 0x20, 0x30))
    para("CAREER HIGHLIGHTS", size=11.5, bold=True)
    para("Delivery: Shipped a freight tracker for Northwind Freight.", style="List Bullet")
    para("EXPERIENCE", size=11.5, bold=True)
    para("Engineering Manager  ·  Northwind Freight\t2022 – Present", bold=True)
    para("Led eight engineers.", style="List Bullet")
    doc.save(str(path))
    return path


def texts(path: Path) -> list[str]:
    return [p.text for p in Document(str(path)).paragraphs]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_replace_profile_changes_only_profile(tmp_path):
    master = build_master(tmp_path / "master.docx")
    before = digest(master)
    out = replace_profile(master, tmp_path / "out" / "copy.docx", ["One.", "Two.", "Three."])
    assert digest(master) == before  # the master is never written
    old, new = texts(master), texts(out)
    i = old.index("PROFILE")
    assert new[: i + 1] == old[: i + 1]
    assert new[i + 1 : i + 4] == ["One.", "Two.", "Three."]
    assert new[i + 4 :] == old[i + 3 :]


def test_replace_profile_keeps_the_master_paragraph_format(tmp_path):
    master = build_master(tmp_path / "master.docx")
    out = replace_profile(master, tmp_path / "copy.docx", ["One.", "Two.", "Three."])
    paras = Document(str(out)).paragraphs
    i = [p.text for p in paras].index("PROFILE")
    for p in paras[i + 1 : i + 4]:
        assert len(p.runs) == 1
        assert p.runs[0].font.size == Pt(10.5)
        assert p.runs[0].font.color.rgb == RGBColor(0x10, 0x20, 0x30)
        assert not p.runs[0].bold


@pytest.mark.parametrize("kwargs, words", [
    ({"profile_heading": None}, "no PROFILE"),
    ({"twice": True}, "more than one"),
    ({"body": 0}, "no paragraph"),
])
def test_replace_profile_refuses_what_it_cannot_place(tmp_path, kwargs, words):
    master = build_master(tmp_path / "master.docx", **kwargs)
    with pytest.raises(DocxError) as exc:
        replace_profile(master, tmp_path / "copy.docx", ["One."])
    assert "master.docx" in str(exc.value) and words in str(exc.value)
    assert not (tmp_path / "copy.docx").exists()


def test_master_on_page_reads_highlights_and_bullets(tmp_path):
    from jobagent.services.masters import master_on_page

    on_page = master_on_page(build_master(tmp_path / "master.docx"))
    assert on_page == {
        "master highlight 1": "Delivery: Shipped a freight tracker for Northwind Freight.",
        "master bullet 1": "Led eight engineers.",
    }
    assert master_on_page(tmp_path / "missing.docx") == {}


# --------------------------------------------------------------------------- #
# T010: build_profile, the longer PROFILE as cited sentences
# --------------------------------------------------------------------------- #

from datetime import datetime, timezone

from jobagent.adapters.llm import LLMClient, LLMResponse, Provider
from jobagent.core.generate import build_profile
from jobagent.core.models import FitAssessment, JobDescription, Verdict, WorkArrangement, WorkType
from jobagent.core.profile import load_profile
from jobagent.core.validation import Severity


class Scripted(LLMClient):
    """Returns each payload in turn; remembers every prompt."""

    provider = Provider.anthropic

    def __init__(self, *payloads):
        super().__init__(model="fake-model")
        self.payloads = list(payloads)
        self.prompts: list[str] = []

    def _complete(self, *, system, prompt, max_tokens):  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, *, prompt, label=None, **kwargs):
        self.prompts.append(prompt)
        payload = self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0]
        return payload, LLMResponse(text="{}", provider=self.provider, model=self.model,
                                    input_tokens=1, output_tokens=1)


@pytest.fixture
def sam(profile_factory):
    return load_profile(profile_factory())


@pytest.fixture
def ad() -> JobDescription:
    return JobDescription(
        id=7, title="Engineering Manager", company="Acme Logistics", posted_by="Harbour Talent",
        via_agency=True, work_type=WorkType.permanent, work_arrangement=WorkArrangement.hybrid,
        raw_text="Harbour Talent is recruiting an Engineering Manager for Acme Logistics.",
        ingested_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def fit() -> FitAssessment:
    return FitAssessment(
        jd_id=7, overall_score=72, recruiter_screen_score=65, verdict=Verdict.apply,
        rationale="Good match.", target_role_match=True, target_role_note="EM.",
        scored_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )


def para(*sentences):
    return [{"text": text, "cites": cites} for text, cites in sentences]


GOOD = {"paragraphs": [
    para(("Engineering manager for product teams.", ["recent_manager"])),
    para(("I recruited and onboarded 9 people for a 15-person team.", ["recent_manager.0"])),
    para(("I am looking for a permanent engineering manager role.", ["ad"])),
]}


def long_answer(words: int) -> dict:
    return {"paragraphs": [para((" ".join(["engineering"] * (words - 1)) + ".", ["recent_manager"]))]}


def blockers(written):
    return [i for i in written.issues if i.severity is Severity.blocker]


def test_build_profile_returns_the_cited_paragraphs(sam, ad, fit):
    client = Scripted(GOOD)
    written = build_profile(ad, sam, fit, client=client)
    assert [len(p) for p in written.paragraphs] == [1, 1, 1]
    assert written.text.startswith("Engineering manager for product teams.")
    assert not blockers(written)
    prompt = client.prompts[0]
    assert "at most 250 words" in prompt and "{" + "long_profile_rules}" not in prompt


def test_build_profile_over_250_words_is_rewritten_once_then_blocked(sam, ad, fit):
    client = Scripted(long_answer(260), long_answer(260))
    written = build_profile(ad, sam, fit, client=client)
    assert len(client.prompts) == 2
    assert "250" in client.prompts[1].split(client.prompts[0], 1)[-1]
    assert any("250" in i.detail for i in blockers(written))
    assert len(written.rejected) == 1


def test_build_profile_rejects_an_unknown_citation(sam, ad, fit):
    bad = {"paragraphs": [para(("Ran a team.", ["no_such_entry.0"]))]}
    written = build_profile(ad, sam, fit, client=Scripted(bad))
    assert blockers(written)


def test_build_profile_must_not_repeat_the_master(sam, ad, fit):
    line = "I recruited and onboarded 9 people for a 15-person team."
    written = build_profile(ad, sam, fit, client=Scripted(GOOD),
                            on_page={"master bullet 1": line})
    assert any(i.rule == "PROFILE repeats the resume" for i in blockers(written))


def test_build_profile_rejects_third_person(sam, ad, fit):
    third = {"paragraphs": [para(("He led a team of 15.", ["recent_manager.0"]))]}
    written = build_profile(ad, sam, fit, client=Scripted(third))
    assert [i.rule for i in blockers(written)] == ["third person"]
    # Re-checked on a repair too: the recheck carries the extra check.
    fixed = written.recheck([[written.paragraphs[0][0].model_copy(update={"text": "I led a team of 15."})]])
    assert not [i for i in fixed if i.rule == "third person"]


# --------------------------------------------------------------------------- #
# T020: a custom resume with the longer profile
# --------------------------------------------------------------------------- #

from jobagent.core.generate import build_resume


def selection_with_profile(profile, words: int) -> dict:
    first = profile.roles.roles[0]
    return {
        "tagline": "Engineering Leader  ·  Platform",
        "profile_paragraphs": [" ".join(["delivery"] * words) + "."],
        "profile_refs": [[profile.roles.roles[-1].id]],
        "highlights": [],
        "skill_categories": list(profile.roles.skills)[:6],
        "roles": [{"role_id": first.id, "bullet_refs": [f"{first.id}.0"]}],
        "earlier_career_ids": [],
    }


def profile_length(built):
    return [i for i in built.issues if i.rule == "PROFILE length"]


@pytest.mark.parametrize("words, blocked", [(250, False), (251, True)])
def test_custom_long_profile_word_limit(sam, ad, fit, words, blocked):
    client = Scripted(selection_with_profile(sam, words))
    built = build_resume(ad, sam, fit, client=client, long_profile=True)
    assert bool(profile_length(built)) is blocked
    assert "at most 250 words" in client.prompts[0]
    assert SHORT_PROFILE_RULE not in client.prompts[0]


def test_custom_short_profile_is_unchanged(sam, ad, fit):
    client = Scripted(selection_with_profile(sam, 251))
    built = build_resume(ad, sam, fit, client=client)
    assert not profile_length(built)
    assert SHORT_PROFILE_RULE in client.prompts[0]
    assert "at most 250 words" not in client.prompts[0]


# --------------------------------------------------------------------------- #
# T013-T015: services.documents.generate with a master and a longer profile
# --------------------------------------------------------------------------- #

from jobagent.adapters.llm import RunContext
from jobagent.config import Config
from jobagent.core.generate import GeneratedText, Sentence
from jobagent.services import documents
from jobagent.services.refusals import MasterProfileMissing, NoMasterForProfile
from jobagent.services.workspace import Workspace
from tests.ui_seed import TODAY, masters_profile, seed, workspace

CONFIG = Config(_env_file=None, llm_default="anthropic:claude-sonnet-5")
NOW = datetime(2026, 9, 29, 14, 0, 0)
PROFILE_TEXT = ["I run engineering teams that ship.", "I am after a permanent manager role."]


@pytest.fixture
def mws(tmp_path):
    profile = masters_profile(tmp_path)
    for name in ("Sam-Resume-Manager.docx", "Sam-Resume-AI.docx", "Sam-Resume-Contract.docx"):
        build_master(profile / "resumes" / name)
    base = workspace(tmp_path)
    return Workspace(**{**base.__dict__, "profile_dir": profile})


@pytest.fixture
def mids(mws):
    return seed(mws)


class Model:
    """Fakes for every paid step; counts what ran."""

    def __init__(self, monkeypatch, *, profiles=None, pages=None, claims=None):
        self.calls: list[str] = []
        self.feedback: list[str | None] = []
        self.profiles = list(profiles or [PROFILE_TEXT])
        self.pages = list(pages or [None])
        self.claims = list(claims or [[]])
        monkeypatch.setattr(documents, "get_client", lambda *a, **k: object())
        monkeypatch.setattr(documents.role_kind, "ensure", lambda *a, **k: None)
        monkeypatch.setattr(documents, "build_profile", self.build_profile)
        monkeypatch.setattr(documents, "count_pages", self.count_pages)
        monkeypatch.setattr(documents.checks, "check_claims", self.check_claims)

    def _next(self, items):
        return items.pop(0) if len(items) > 1 else items[0]

    def build_profile(self, jd, profile, assessment, *, client, feedback=None, **_):
        self.calls.append("profile")
        self.feedback.append(feedback)
        paragraphs = [[Sentence(text=t, cites=["recent_manager"])] for t in self._next(self.profiles)]
        return GeneratedText(text="\n\n".join(p[0].text for p in paragraphs), paragraphs=paragraphs)

    def count_pages(self, path):
        return self._next(self.pages)

    def check_claims(self, *a, **k):
        self.calls.append("claims")
        return self._next(self.claims)


def go(ws, jd_id, **kw):
    options = dict(resume=False, cover=False, questions=[], today=TODAY, now=NOW)
    options.update(kw)
    return documents.generate(ws, CONFIG, RunContext(command="generate", jd_id=jd_id), jd_id, **options)


def resume_file(result):
    return next(p for p in result.written if "_Resume_" in p.name)


def test_master_profile_writes_a_copy_with_only_profile_changed(mws, mids, monkeypatch):
    model = Model(monkeypatch)
    master = mws.profile_dir / "resumes" / "Sam-Resume-Manager.docx"
    before = digest(master)
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    out = resume_file(result)
    assert out.name == documents.docs.document_name("Resume", documents._load(mws, mids["acme"]).jd, when=TODAY)
    assert digest(master) == before
    old, new = texts(master), texts(out)
    i = old.index("PROFILE")
    assert new[i + 1 : i + 3] == PROFILE_TEXT
    assert new[: i + 1] == old[: i + 1] and new[i + 3 :] == old[i + 3 :]
    # The plain master is not copied as well: the copy replaces it.
    assert not any(p.name.startswith("Sam-Resume") for p in result.written)
    assert result.resume_base == ("manager", True)
    assert documents.latest_resume_kind(mws, documents._load(mws, mids["acme"]).jd, TODAY) == ("manager", True)
    assessment = (result.folder / "assessment.md").read_text()
    assert "copy of the Engineering Manager master with a longer profile" in assessment
    assert model.calls == ["profile", "claims"]


def test_master_profile_uses_the_named_master(mws, mids, monkeypatch):
    Model(monkeypatch)
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile, master="ai")
    assert result.resume_base == ("ai", True)


def test_master_profile_refused_when_no_master_fits(mws, mids, monkeypatch):
    monkeypatch.setattr(documents.masters, "choose",
                        lambda *a, **k: documents.masters.MasterChoice(reason="Not a target: hands-on, permanent."))
    monkeypatch.setattr(documents, "get_client", lambda *a, **k: pytest.fail("spent"))
    with pytest.raises(NoMasterForProfile) as refused:
        go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    assert "Not a target" in str(refused.value)


def test_master_profile_refused_when_the_master_has_no_profile(mws, mids, monkeypatch):
    build_master(mws.profile_dir / "resumes" / "Sam-Resume-Manager.docx", profile_heading=None)
    monkeypatch.setattr(documents, "get_client", lambda *a, **k: pytest.fail("spent"))
    with pytest.raises(MasterProfileMissing):
        go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)


def test_master_profile_over_three_pages_is_shortened_once(mws, mids, monkeypatch):
    model = Model(monkeypatch, pages=[3.2, 2.9])
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    assert model.calls.count("profile") == 2
    assert "at most" in model.feedback[1] and "3.20 pages" in model.feedback[1]
    assert "_NOT-READY" not in resume_file(result).name
    assert result.resume_pages == 2.9


def test_master_profile_still_over_is_not_ready(mws, mids, monkeypatch):
    model = Model(monkeypatch, pages=[3.2, 3.1])
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    assert model.calls.count("profile") == 2
    assert "_NOT-READY" in resume_file(result).name
    assert any(i.rule == "resume length" for i in result.issues)


def test_profile_target_words():
    assert documents.profile_target_words(250, 3.1, 3.0) == 250 - 56 - 10
    assert documents.profile_target_words(120, 3.9, 3.0) == documents.MIN_PROFILE_WORDS


def test_master_kind_copies_the_suggested_master_free(mws, mids, monkeypatch):
    monkeypatch.setattr(documents, "get_client", lambda *a, **k: pytest.fail("spent"))
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master)
    assert result.copied_only
    assert [p.name for p in result.written] == ["Sam-Resume-Manager.pdf"]


def test_plan_lists_the_resume_not_the_master(mws, mids):
    planned = documents.plan(mws, mids["acme"], resume=False, cover=False, answers=False,
                             when=TODAY, resume_kind=ResumeKind.master_profile)
    assert any("_Resume_" in n for n in planned.names)
    assert not any(n.startswith("Sam-Resume") for n in planned.names)


def test_custom_profile_asks_the_resume_call_for_the_longer_profile(mws, mids, monkeypatch):
    from types import SimpleNamespace

    seen = {}

    def build_resume(jd, profile, assessment, *, client, today, long_profile=False, **_):
        seen["long_profile"] = long_profile
        return SimpleNamespace(content="resume content", issues=[], unused=[])

    Model(monkeypatch)
    monkeypatch.setattr(documents, "build_resume", build_resume)
    def write_resume(content, path):
        path.write_bytes(b"x")
        return path

    monkeypatch.setattr(documents, "write_resume", write_resume)
    result = go(mws, mids["acme"], resume_kind=ResumeKind.custom_profile)
    assert seen["long_profile"] is True
    assert result.resume_base == ("custom", True)


def test_long_profile_length_feedback_names_the_profile_first():
    from jobagent.core.generate import FULL_TIME_LENGTH

    assert "shorten the PROFILE first" in documents.length_feedback(3.3, FULL_TIME_LENGTH, long_profile=True)
    assert "PROFILE" not in documents.length_feedback(3.3, FULL_TIME_LENGTH)


# --------------------------------------------------------------------------- #
# T018: the longer profile is held to the profile's evidence, end to end
# --------------------------------------------------------------------------- #

from jobagent.services.checks import Mismatch
from tests.conftest import edit_yaml


def real_writer(monkeypatch, *payloads, claims=None, repairs=None):
    """The real build_profile and checks, a scripted model, faked claim check and repair."""
    client = Scripted(*payloads)
    state = {"claims": list(claims or [[]]), "repairs": list(repairs or [None])}

    def check_claims(*a, **k):
        items = state["claims"]
        return items.pop(0) if len(items) > 1 else items[0]

    def repair_sentences(*a, **k):
        items = state["repairs"]
        return items.pop(0) if len(items) > 1 else items[0]

    monkeypatch.setattr(documents, "get_client", lambda *a, **k: client)
    monkeypatch.setattr(documents.role_kind, "ensure", lambda *a, **k: None)
    monkeypatch.setattr(documents.checks, "check_claims", check_claims)
    monkeypatch.setattr(documents.checks, "repair_sentences", repair_sentences)
    return client


def rules(result):
    return {i.rule: i.severity.value for i in result.issues}


def test_never_in_documents_evidence_is_refused(mws, mids, monkeypatch):
    def hide(data):
        role = next(r for r in data["roles"] if r["id"] == "recent_manager")
        role["bullets"][3]["never_in_documents"] = True
    edit_yaml(mws.profile_dir / "roles.yaml", hide)
    payload = {"paragraphs": [para(("I resolved a performance problem with weekly check-ins.",
                                    ["recent_manager.3"]))]}
    real_writer(monkeypatch, payload)
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    assert "_NOT-READY" in resume_file(result).name
    assert any(i.severity.value == "blocker" and "recent_manager.3" in (i.detail + i.excerpt)
               for i in result.issues)


def test_banned_phrase_is_a_blocker(mws, mids, monkeypatch):
    payload = {"paragraphs": [para(("I am the ideal candidate for this role.", ["recent_manager"]))]}
    real_writer(monkeypatch, payload)
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    assert "_NOT-READY" in resume_file(result).name


def test_an_untraced_figure_is_flagged(mws, mids, monkeypatch):
    payload = {"paragraphs": [para(("I led a team of 47 engineers.", ["recent_manager.0"]))]}
    real_writer(monkeypatch, payload)
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    assert any("47" in (i.detail + i.excerpt) for i in result.issues)


def test_an_em_dash_is_a_warning(mws, mids, monkeypatch):
    payload = {"paragraphs": [para(("I led a 15-person engineering team — across three product lines.",
                                    ["recent_manager.0"]))]}
    real_writer(monkeypatch, payload)
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    dashes = [i for i in result.issues if "dash" in i.rule.lower()]
    assert dashes and all(i.severity.value == "warning" for i in dashes)


GOOD_SENTENCE = "I recruited and onboarded 9 people for a 15-person team."


def test_a_flagged_sentence_is_repaired_alone(mws, mids, monkeypatch):
    payload = {"paragraphs": [para((GOOD_SENTENCE, ["recent_manager.0"]))]}
    fixed = "I recruited and onboarded 9 people."
    client = real_writer(
        monkeypatch, payload,
        claims=[[Mismatch(sentence=GOOD_SENTENCE, problem="Team size not in the cited bullet.")], []],
        repairs=[{GOOD_SENTENCE: fixed}],
    )
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    assert len(client.prompts) == 1  # no full rewrite
    assert fixed in texts(resume_file(result))
    assert "sentence repaired" in rules(result)


def test_a_failed_repair_rewrites_once_with_the_mismatch_named(mws, mids, monkeypatch):
    payload = {"paragraphs": [para((GOOD_SENTENCE, ["recent_manager.0"]))]}
    client = real_writer(
        monkeypatch, payload,
        claims=[[Mismatch(sentence=GOOD_SENTENCE, problem="Says more than its evidence.")], []],
        repairs=[None],
    )
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    assert len(client.prompts) == 2
    assert "Says more than its evidence." in client.prompts[1]
    assert "_NOT-READY" not in resume_file(result).name


def test_no_claim_check_when_switched_off(mws, mids, monkeypatch):
    payload = {"paragraphs": [para((GOOD_SENTENCE, ["recent_manager.0"]))]}
    real_writer(monkeypatch, payload)
    monkeypatch.setattr(documents.checks, "check_claims", lambda *a, **k: pytest.fail("checked"))
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile, check_claims=False)
    assert result.claims is None


# --------------------------------------------------------------------------- #
# T024: what went is resolved with the longer-profile flag
# --------------------------------------------------------------------------- #

from jobagent.services.masters import resolve_sent


def test_named_master_with_long_profile(mws, mids):
    sent = resolve_sent(mws, mids["acme"], chosen="manager", long_profile=True, today=TODAY)
    assert (sent.master, sent.long_profile, sent.file) == ("manager", True, None)
    assert sent.suggested == "manager"


def test_named_custom_with_long_profile(mws, mids):
    sent = resolve_sent(mws, mids["acme"], chosen="custom", long_profile=True, today=TODAY)
    assert (sent.master, sent.long_profile) == ("custom", True)


def test_nothing_named_is_the_suggested_master_without_it(mws, mids):
    sent = resolve_sent(mws, mids["acme"], today=TODAY)
    assert (sent.master, sent.long_profile, sent.assumed) == ("manager", False, True)


def test_sent_as_generated_reads_the_generated_record(mws, mids, monkeypatch):
    Model(monkeypatch)
    go(mws, mids["acme"], resume_kind=ResumeKind.master_profile, master="ai")
    sent = resolve_sent(mws, mids["acme"], sent_as_generated=True, today=TODAY)
    assert (sent.master, sent.long_profile) == ("ai", True)


def test_an_edited_copy_reads_the_generated_record(mws, mids, monkeypatch, tmp_path):
    Model(monkeypatch)
    result = go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    edited = tmp_path / "edited.docx"
    edited.write_bytes(resume_file(result).read_bytes() + b"edit")
    sent = resolve_sent(mws, mids["acme"], sent_resume=edited, today=TODAY)
    assert (sent.master, sent.long_profile) == ("manager", True)


def test_a_file_identical_to_a_master_is_that_master(mws, mids, monkeypatch):
    Model(monkeypatch)
    go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    master = build_master(mws.profile_dir / "resumes" / "Sam-Resume-AI.docx", body=3)
    sent = resolve_sent(mws, mids["acme"], sent_resume=master, today=TODAY)
    assert (sent.master, sent.long_profile) == ("ai", False)


def test_without_a_record_a_generated_resume_is_custom(mws, mids):
    sent = resolve_sent(mws, mids["acme"], sent_as_generated=True, today=TODAY)
    assert (sent.master, sent.long_profile) == ("custom", None)


# --------------------------------------------------------------------------- #
# T029: revise does not rebuild a master copy as a custom resume
# --------------------------------------------------------------------------- #

from jobagent.core.models import DocumentKind
from jobagent.services import revise
from jobagent.services.refusals import MasterCopyNotRevisable


def test_revise_refuses_a_master_copy(mws, mids, monkeypatch):
    Model(monkeypatch)
    go(mws, mids["acme"], resume_kind=ResumeKind.master_profile)
    with pytest.raises(MasterCopyNotRevisable) as refused:
        revise.plan(mws, mids["acme"], DocumentKind.resume, TODAY)
    assert refused.value.master == "Engineering Manager"
    assert revise.revisable(mws, mids["acme"], TODAY) == []
