---
description: "Task list for 003 generation quality"
---

# Tasks: Generation Quality

**Input**: `specs/003-generation-quality/` (plan.md, spec.md, research.md,
data-model.md, contracts/cli-and-services.md, quickstart.md)

**Tests**: requested. quickstart.md names a test file per success criterion,
and the model is mocked in every one (Constitution IV).

**Examples**: invented only (Constitution VI). The worked example is
"Northwind Freight, Engineering Manager", people-focused; Alan's real profile
and answer bank never enter the repo.

**Commits**: one per task, `003 T0xx: …`.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [X] T001 Create the invented worked example in `tests/quality_seed.py`: a people-focused Northwind Freight Engineering Manager `JobDescription` (must-haves led by coaching, 1:1s, "addressing underperformance with care"; an about-us sentence "We build route planning for regional freight"), a `FitAssessment` whose `requirements[]` carry `met`/`partial` rows with `evidence_ref`s that exist in `profile.example/`, one `gap` row, and the original faulty documents as plain text (resume opening on managing out an underperformer, one story used four times, a letter stating an acquisition the profile does not hold, two people merged into one). A second ad, technical-lead, for the contrast case; a third with no company description.

---

## Phase 2: Foundational (blocks every story)

- [X] T002 In `jobagent/core/models.py` add `RoleKind(str, Enum)` with exactly `people_focused`, `delivery_focused`, `technical_lead`, `ai_enablement`; `exclude_for: list[RoleKind] = []` on `Story`, `Bullet`, `Role`, `FounderEntry`, `AiCapabilityEntry`, `EarlierRole`; `QuestionType(str, Enum)` with exactly `summary, why_company, why_role, why_you, what_made_you_apply, salary_expectation, notice_period, right_to_work, why_leaving`; `StoriesFile.answers: dict[QuestionType, str] = {}`; and `RoleClassification(_Base)` with `primary: RoleKind`, `secondary: RoleKind | None = None`, `reason: str`.
- [X] T003 In `jobagent/core/store.py` bump `SCHEMA_VERSION` to 11 and add nullable TEXT columns `role_kind`, `role_kind_secondary`, `role_kind_reason` to `job_descriptions` ("NULL until first needed"); add `get_role_kind(conn, jd_id) -> RoleClassification | None` and `set_role_kind(conn, jd_id, c)`; `update_jd` (the amend path) clears all three ("an amendment clears all three (the ad changed)").
- [X] T004 In `jobagent/adapters/llm.py` add `CallType.classify` and `CallType.review`, routed from new `Config.llm_classify` / `Config.llm_review` (`jobagent/config.py`), each falling back to `LLM_DEFAULT` like the others; add `Config.check_claims: bool = True` and `Config.review: bool = True`; document the four in `.env.example`.
- [X] T005 [P] In `profile.example/` (invented): mark one story `exclude_for: [people_focused]` plus a bullet that links to it; add an `answers:` bank with three invented entries (`summary`, `why_leaving`, `notice_period`); confirm `load_profile` accepts both and rejects an unknown kind.
- [X] T006 Tests for T002–T005 in `tests/test_profile.py`, `tests/test_store.py` (migration v10→v11 keeps rows; amend clears the kind), `tests/test_llm.py` (routing and fallback).

**Checkpoint**: schema in place; nothing behaves differently yet.

---

## Phase 3: User Story 1 — documents fit the kind of role (P1) 🎯 MVP

**Goal**: classify each ad once; the kind decides lead evidence, skills order and exclusions.

**Independent test**: mocked model; a people-focused ad gives a resume whose profile paragraph and first highlight come from people evidence, and the excluded story appears nowhere.

- [X] T007 [P] [US1] Write `prompts/classify_role.md`: inputs title, must-haves, responsibilities, nice-to-haves (never raw text); output JSON `{"primary": kind, "secondary": kind|null, "reason": "<one sentence>"}`; the four kinds defined by what the ad leads with; tie-breaking rule (what the first must-haves ask for).
- [X] T008 [US1] Create `jobagent/services/role_kind.py`: `ensure(ws, config, ctx, jd_id) -> RoleClassification` returns the stored value free, otherwise calls `CallType.classify` through `get_client`, validates, stores, returns; `stored(ws, jd_id)` reads only; `needs_classify(ws, jd_id) -> bool` for estimates.
- [X] T009 [P] [US1] Create `jobagent/core/roles.py` (pure): `excluded_kinds(c)` = primary + secondary; `excluded_ids(profile, kinds) -> set[str]` (story ids, entry ids, `entry.index` bullet ids, and bullets whose `linked_story` is excluded); ids stay stable, so bullets are skipped, never removed and renumbered; `classify(jd, client)` makes the call; `SKILL_ORDER: dict[RoleKind, list[str]]` of tag-like keywords used to order skill categories; `order_skills(keys, kind)`; `LEAD_TAGS: dict[RoleKind, set[str]]` (people_focused: leadership, hiring, coaching, mentoring, people; technical_lead: architecture, replatforming, technical; delivery_focused: delivery, agile, process; ai_enablement: ai, llm).
- [X] T010 [US1] In `jobagent/core/generate.py`: `build_resume`, `build_cover_letter`, `build_answers` take `kind: RoleClassification | None`; when set, catalogue, citable set and stories skip `roles.excluded_ids(...)`; the role kind and its reason are passed to the prompts; `_assemble` orders skill categories with `roles.order_skills` when the kind is set; a cited or bullet ref in `excluded_ids` is a blocker `excluded evidence`; a first highlight whose source carries no `LEAD_TAGS[kind.primary]` tag is a warning `lead not on-kind`.
- [X] T011 [P] [US1] In `prompts/generate_resume.md`, `prompts/generate_cover_letter.md`, `prompts/generate_answers.md` add a `{role_kind}` block with per-kind guidance (people_focused: profile paragraph and first highlight from people evidence, AI limited to one clause unless the ad asks; technical_lead: technical depth leads; delivery_focused: delivery record leads; ai_enablement: AI work leads).
- [X] T012 [US1] In `jobagent/services/documents.py`: `generate` calls `role_kind.ensure` after every refusal and `before_spend`, before the resume; passes the kind to every builder; `GenerateResult.role_kind` (`jobagent/services/results.py`); `assessment.md` (`adapters/docs.assessment_markdown`) shows the kind and reason; `GeneratePlan.needs_classify`.
- [X] T013 [US1] Show the kind with the assessment: `jobagent/services/scoring.py` calls `role_kind.ensure` after a successful score; `jobagent/cli/score.py` prints `Role kind: people-focused (secondary …) — <reason>`; `jobagent/web/templates/detail.html` shows the stored kind when present.
- [X] T014 [US1] In `jobagent/services/costs.py` add action `classify` (label `classify_role`, `CallType.classify`), and let one estimate combine labels routed to different call types (each label priced on its own route's model); `generate` and `score` estimates include `classify_role` when `needs_classify`.
- [X] T015 [P] [US1] Tests: `tests/test_roles.py` (filtering, linked-story bullets, secondary kind, skills order); `tests/test_role_kind.py` (classify once, stored thereafter, amend reclassifies, bad JSON → error without storing); `tests/test_generate_quality.py` (SC-001 part one: Northwind fixture → excluded story absent from the prompt and blocked if cited; lead warning; technical-lead contrast).

**Checkpoint**: US1 independently testable.

---

## Phase 4: User Story 2 — every must-have evidenced on the resume (P1)

**Goal**: coverage from the stored assessment; missing → blocker; skills-only → weak.

**Independent test**: four must-haves, three evidenced → three on the resume, one gap.

- [X] T016 [P] [US2] Create `jobagent/core/coverage.py` (pure): `CoverageRow(requirement, evidence_ref, status: "covered"|"weak"|"missing"|"gap", where: list[str])`; `must_cover(assessment, excluded) -> list[(requirement, ref)]` from `requirements[]` with status `met`/`partial` and an `evidence_ref` not excluded; `coverage(rows, cited_refs, skills_text) -> list[CoverageRow]` where a ref counts as cited if a highlight or role bullet cites it, its entry, or a bullet within it; skills-table hit only → `weak`; `issues(rows)` → blocker `must-have missing`, warning `covered weakly`.
- [X] T017 [US2] In `jobagent/core/generate.py` pass the must-cover list into the resume prompt (`{must_cover}`), compute `GeneratedResume.coverage`, add its issues; gap rows from the assessment listed as `gap`, never filled.
- [X] T018 [P] [US2] In `prompts/generate_resume.md` add the must-cover block: each listed requirement must be answered by a highlight or role bullet citing the listed evidence.
- [X] T019 [US2] Surface coverage: `GenerateResult.coverage`; `jobagent/cli/generate.py` prints a coverage table (must-have → where / weak / gap); `assessment.md` gains a Coverage section; the UI run result shows it.
- [X] T020 [P] [US2] Tests `tests/test_coverage.py` (SC-003: evidenced must-haves all on the resume; missing → blocker; skills only → weak; gap stays gap; excluded evidence not demanded).

---

## Phase 5: User Story 3 — prose stays faithful (P1)

**Goal**: letter and answers come back as cited sentences, checked in code; optional paid claim check.

**Independent test**: unknown id fails; no citation fails; ad framing citing `"ad"` passes.

- [X] T021 [US3] In `jobagent/core/validation.py` add `check_citations(paragraphs, known: set[str]) -> list[ValidationIssue]`: every sentence needs ≥1 cite (blocker `uncited claim`); every cite must be in `known` or be `"ad"` (blocker `unknown citation`); `known` = filtered citable ids ∪ story ids ∪ explanations keys ∪ answer-bank keys.
- [X] T022 [US3] In `jobagent/core/generate.py` change the letter contract to `{"paragraphs": [[{"text": str, "cites": [str, …]}]]}` (`_Sentence`, `_Letter` models); `build_cover_letter` uses `complete_json`, rebuilds `text` by joining sentences into paragraphs (salutation/sign-off stripping still applied to the first and last sentence), runs `validate_prose` on the rebuilt text and `check_citations` on the sentences, regenerates once on blockers; `GeneratedText` gains `sentences: list[_Sentence]`.
- [X] T023 [P] [US3] Rewrite the output section of `prompts/generate_cover_letter.md` for the JSON contract: every sentence cites ids from the catalogue or stories, `"ad"` for framing the ad; never state a fact no cited evidence holds.
- [X] T024 [P] [US3] Write `prompts/check_claims.md`: input is each sentence with the full text of each cited item; output `{"mismatches": [{"sentence": str, "problem": str}]}`; problems: overstated, merged people, wrong place or employer, detail not in evidence.
- [X] T025 [US3] Create `jobagent/services/checks.py` with `NotChecked(reason)` and `check_claims(config, ctx, sentences, evidence: dict[str, str]) -> list[Mismatch] | NotChecked` on `CallType.review` with label `check_claims`; never raises on a model failure; `evidence_text(profile, id)` resolves an id to its text (bullet, entry, story, explanation, bank entry; `"ad"` → skipped).
- [X] T026 [US3] In `jobagent/services/documents.py` add `check_claims: bool = True` to `generate`; run after the letter (and answers) pass the code checks; mismatches become blocker issues `claim mismatch`; `GenerateResult.claims`.
- [X] T027 [P] [US3] Tests `tests/test_citations.py` (SC-002; seeded "acquisition" test: the profile lacks it, a sentence citing a story that lacks it is flagged by the mocked claim check and the word is absent from a clean letter) and claim-check failure → `NotChecked` with documents still written.

---

## Phase 6: User Story 4 — independent review before "ready" (P2)

**Goal**: a reviewer that sees ad, policies and documents only; blocking → not ready.

**Independent test**: mocked reviewer returns a blocker → not ready, listed; none → ready.

- [X] T028 [P] [US4] Write `prompts/review_policies.md` (the four hard rules, the age-signal policy, story-reuse caps, the standing decisions: one gap sentence, founder years, master format) and `prompts/review_documents.md` (inputs: parsed ad, policies, `voice.md` banned list, the kind's exclusions by label, each document's rendered text; output `{"blocking": [{"document", "finding"}], "suggestions": [...]}`; reads as a hiring manager for this kind of role and as a policy checker; never shown the writer prompts or scorer notes).
- [X] T029 [US4] In `jobagent/services/checks.py` add `NotReviewed(reason)` and `review(config, ctx, jd, documents: dict[str, str], policies: str, banned: list[str]) -> Review | NotReviewed` on `CallType.review`, label `review_documents`.
- [X] T030 [US4] In `jobagent/services/documents.py`: `review: bool = True`; render each document's text (resume via a plain-text rendering of `ResumeContent`, letter text, answers text); run review last; write `review.md` into the folder; `GenerateResult.ready` = no blockers among issues and review not blocking, `False` when not reviewed; `GenerateResult.review`.
- [X] T031 [US4] In `jobagent/cli/generate.py` add `--no-check-claims` and `--no-review` (defaults from config); estimate line lists each part; after the run print **Ready** / **Not ready** / **Not reviewed**, then blocking findings, then suggestions.
- [X] T032 [US4] In `jobagent/services/costs.py` add actions `check_claims` and `review` (labels `check_claims`, `review_documents` on `CallType.review`); `labels_for("generate", …, check_claims=…, review=…)`; an unmeasured label states "not yet measured" rather than hiding the total (unchanged rule: no partial sums).
- [X] T033 [US4] Web: `jobagent/web/templates/generate_confirm.html` shows two ticked boxes (claim check, review) each with its cost; `jobagent/web/routes.py` and `work.py` pass them through; the run result shows Ready/Not ready and the review.
- [X] T034 [P] [US4] Tests: `tests/test_checks.py` (SC-004: the worked example's original documents with a mocked reviewer; prompt contains the policies and the documents and not the writer prompt or any `note_for_scorer`; failure → `NotReviewed`, ready False); `tests/test_cli_generate.py` and `tests/test_web_generate.py` (flags, readiness line, boxes).

---

## Phase 7: User Story 5 — story reuse and defensive phrasing capped (P2)

**Independent test**: a story in profile paragraph + highlight + bullet fails; "this ad is asking for" fails.

- [X] T035 [US5] In `jobagent/core/validation.py` add `story_of(ref, profile) -> str | None` (story id itself, or a bullet's `linked_story`, or an entry whose bullets link one only when cited as a bullet) and `check_story_reuse(uses: dict[str, list[str]], *, cap: int, context)` → blocker `story reused`; in `generate.py` the resume selection gains `profile_refs: list[list[str]]` (one list per profile paragraph); resume: ≤2 uses and never profile + bullet together; letter: ≤1; one form's answers: ≤1 per story.
- [X] T036 [P] [US5] In `prompts/generate_resume.md` add `profile_refs` to the contract and the reuse caps to the rules.
- [X] T037 [US5] In `jobagent/core/validation.py` add a contrast-phrasing count: more than one `not X but Y` / `not just X` / `rather than` construction per document → warning `contrast phrasing`.
- [X] T038 [US5] Banned phrases: add to `profile.example/voice.md` the invented-safe list ("not a claim", "not advisory", "full management authority", "this ad is asking for", "your ad asks for"); propose the same lines for Alan's `profile/voice.md` and apply only with his agreement (his file, gitignored).
- [X] T039 [P] [US5] Tests in `tests/test_validation.py` and `tests/test_generate_quality.py` (SC-001 part two: four uses of one story → blocker; profile+bullet → blocker; letter reuse; contrast warning; banned phrase blocker).

---

## Phase 8: User Story 7 — answers from an answer bank (P2)

**Independent test**: four questions, 600-character limit → four answers within the limit, short and long, no story twice, every claim traced.

- [X] T040 [US7] In `jobagent/core/generate.py` change `build_answers` to the contract `{"answers": [{"question", "type", "short": [sentences], "long": [sentences]}]}` (sentences as in T022); `limit: int | None` checked in code on each variant's rebuilt text (blocker `answer over limit`); `check_citations` per variant; story reuse ≤1 across the form (counting each story once per answer, short and long together); `why_company`-type answers may cite only `"ad"`; the bank entry for each type and the `limit` passed to the prompt; returns `GeneratedAnswers` with a markdown rendering (question, short, long).
- [X] T041 [P] [US7] Rewrite `prompts/generate_answers.md`: classify each question to a type, start from the bank entry when there is one, short and long variants within `{limit}`, JSON contract with cites, no story twice across the form.
- [X] T042 [US7] `jobagent/cli/generate.py` `--limit N` (requires `--answers`); `services/documents.generate(..., limit=None)`; `answers.md` written from the rendering; the claim check (T026) covers answers too.
- [X] T043 [US7] Web: in `generate_confirm.html` the cover letter starts unticked; an answers box (questions textarea, optional limit) passes through to `generate`.
- [X] T044 [P] [US7] Tests `tests/test_answers.py` (SC-005; bank entry reaches the prompt; over-limit → blocker and one regenerate; why-company citing profile evidence → blocker) and the unticked letter in `tests/test_web_generate.py`.

---

## Phase 9: User Story 6 — a letter knows who it is written to (P3)

**Independent test**: an ad describing route planning yields one sentence naming it; an ad without a company description yields none.

- [X] T045 [US6] Letter contract: a sentence about the employer cites `"ad"` and carries `quote`, a verbatim span of the ad; in `generate.py` check the quote occurs in `jd.raw_text` (whitespace- and case-normalised) → else blocker `company claim not in ad`; more than one quoted sentence → warning.
- [X] T046 [P] [US6] `prompts/generate_cover_letter.md`: one company sentence drawn only from the ad's own words, with its `quote`; none when the ad says nothing about the company.
- [X] T047 [P] [US6] Tests in `tests/test_generate_quality.py` (quote present passes; invented quote blocks; second ad with no about-us text and no company sentence passes).

---

## Phase 10: Polish

- [X] T048 README.md: the new flags, the readiness line, the coverage table, the answer bank and `--limit`, the role kind; CLAUDE.md: status, costs table (classify, claim check, review), and the design invariant "excluded evidence is removed from the writer's input, then re-checked on output".
- [ ] T049 Ask Alan, then: his four recent screening answers into `profile/stories.yaml` `answers:`; `exclude_for` on the stories and bullets he named (the testing-lead story for `people_focused`); the voice.md lines from T038.
- [X] T050 Ask Alan first (≈ $0.40): regenerate the real ad behind the worked example into a scratch `OUTPUT_DIR` and compare with the documents he sent (quickstart "Real"); measure the three new prompts with `jobagent spend` and correct the cost estimates in CLAUDE.md.
- [X] T051 Full test run, then a history scan of the branch for real employers, salary figures and never-publish facts before any push.

---

## Dependencies

- Phase 2 blocks everything.
- US1 (Phase 3) before US2, US3, US5, US7: they read the filtered profile and the kind.
- US3's sentence contract (T021–T022) before US5's letter cap, US6 and US7.
- US4 (review) needs the rendered documents of US1–US3; it can land after US3.
- Polish last; T049 and T050 need Alan.

## Parallel opportunities

- Prompts (T007, T011, T018, T023, T024, T028, T036, T041, T046) are separate files.
- Pure modules `core/roles.py` (T009) and `core/coverage.py` (T016) have no shared state.
- Test tasks marked [P] touch their own files.

## Implementation strategy

MVP = Phases 1–3 (role kind and exclusions): it fixes the worst fault of the
worked example on its own. Then US2 and US3 (the other P1s), then the paid
checks (US4), reuse caps (US5), answers (US7), the company sentence (US6).
Each phase ends with the full suite green and one commit per task.
