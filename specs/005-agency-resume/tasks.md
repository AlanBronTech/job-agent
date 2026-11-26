---
description: "Task list for 005 agency resume"
---

# Tasks: Agency Resume (a longer, ad-specific profile)

**Input**: `specs/005-agency-resume/` (spec.md, plan.md, research.md,
data-model.md, contracts/cli.md, contracts/ui.md, quickstart.md)

**Tests**: written before the code in every task that changes behaviour, as
in specs 001-004. Every model call is mocked; the suite strips provider keys.
Tests that need LibreOffice skip without it, as today.

**Examples**: invented only (Constitution VI): Sam Rivera from
`profile.example/`, Harbour Talent, Acme Logistics, Northwind Freight,
Contoso Health. Check each commit's diff for real names before committing.

**Commits**: one per task or per small group; run `uv run pytest -q` after
each.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup (prompts)

- [X] T001 [P] Write `prompts/long_profile_rules.md`: what an agency profile does (answer this ad's main requirements in the ad's order; say what kind of role and engagement is sought; first person as the masters write, never "Alan", "he", "his"; several short paragraphs, no bullets; "at most 250 words"; no em-dash; only from the evidence shown, a gap is left out, never claimed). No placeholders; it is substituted whole into the two prompts below.
- [X] T002 [P] Write `prompts/generate_profile.md` (version 1): inputs `{jd_json}`, `{assessment_json}`, `{role_kind}`, `{catalogue}`, `{stories}`, `{must_have_gaps}`, `{on_page}` (the master's highlights and bullets, "do not repeat these word for word"), `{long_profile_rules}`, `{voice}`; output JSON exactly the letter's shape, `{"paragraphs": [[{"text": "...", "cites": ["entry.id"]}]]}`, every sentence citing at least one id. Model the citation and evidence wording on `prompts/generate_cover_letter.md`.
- [X] T003 In `prompts/generate_resume.md`, replace the body of rule 7 ("PROFILE is two short paragraphs, in the first person …") with the placeholder `{profile_rule}`; move the current text, unchanged, into a constant `SHORT_PROFILE_RULE` in `jobagent/core/generate.py` and pass it from `_ask_for_selection` by default, so output for existing runs is byte-identical (test: the rendered prompt with the default equals the prompt before the change, read from git in the test as a fixture string).

## Phase 2: Foundational

- [X] T004 [P] Add `ResumeKind` (`master`, `master_profile`, `custom`, `custom_profile`) with properties `uses_master` and `long_profile` to `jobagent/core/models.py`; add `Application.resume_long_profile: bool | None = None`. Unit tests in `tests/test_models.py` (or the nearest existing models test file).
- [X] T005 [P] Add `LONG_PROFILE_MAX_WORDS = 250` and `PROFILE_PROMPT = "generate_profile"` to `jobagent/core/generate.py`; add the label `generate_profile` → `CallType.generate` to `_LABEL_CALL` in `jobagent/services/costs.py`, and to `labels_for("generate", …)` via a new `profile=False` argument (test in `tests/test_costs.py`: an unmeasured `generate_profile` is named in `describe()`, never summed as $0).
- [X] T006 Extend the resume record kept by `services/documents._records` (via `ws.documents.keep_record(..., "resume", record)`) with `"base"` (a master id or `"custom"`) and `"long_profile"` (bool); add `latest_resume_kind(ws, jd, today) -> tuple[str, bool] | None` in `jobagent/services/documents.py` that reads the newest resume record and returns None for records without the keys. Tests in `tests/test_docs.py` with a temp job folder.

**Checkpoint**: nothing user-visible yet; full suite green.

---

## Phase 3: User Story 1 - A master copy with a longer profile (P1) 🎯 MVP

**Goal**: `jobagent generate <id> --long-profile` writes a copy of the chosen master with only PROFILE replaced, checked and measured.

**Independent test**: with an invented master .docx built in a fixture and the model mocked, the output differs from the master only in the PROFILE paragraphs, and the master's bytes are unchanged.

- [X] T007 [P] [US1] Tests first in `tests/test_docx_writer.py`: a fixture builds an invented master (name, tagline, contact, `PROFILE` + two `Normal` paragraphs, `CAREER HIGHLIGHTS` + list paragraphs, `EXPERIENCE` …); `replace_profile(master, target, ["One.", "Two.", "Three."])` gives three PROFILE paragraphs with the first body paragraph's run formatting (font size, bold, colour), every other paragraph's text and style identical, and the master's SHA-256 unchanged; refused with `DocxError` naming the file when `PROFILE` is missing, appears twice, or has no body paragraph.
- [X] T008 [US1] Implement `replace_profile(master: Path, target: Path, paragraphs: list[str]) -> Path` in `jobagent/adapters/docx_writer.py` (research R3): open the master, find the paragraph whose stripped text is exactly `PROFILE`, take following paragraphs up to the next heading by the `docx_reader._is_heading` rule (import it; do not copy it), deep-copy the first body paragraph's XML once per new paragraph, keep its first run (set its text), drop other runs, remove the old body paragraphs, save to `target` only.
- [X] T009 [US1] Add `master_on_page(path: Path) -> dict[str, str]` in `jobagent/services/masters.py`: the master's CAREER HIGHLIGHTS and EXPERIENCE bullets as `{"master highlight 1": text, …, "master bullet 1": text, …}` via `adapters/docx_reader.read_sections(path, "resume")`; empty dict if unreadable. Test in `tests/test_masters.py` with the T007 fixture.
- [X] T010 [US1] Tests first in `tests/test_generate.py`: `build_profile(jd, profile, assessment, client=mock, kind=None, on_page={…}, feedback=None, instructions=None, max_words=250)` returns a `GeneratedText` whose paragraphs are the mocked sentences; a mocked 260-word answer is rewritten once with the word failure named, and a second 260-word answer comes back with a `blocker`; a sentence citing an unknown id is a blocker; a sentence repeating an `on_page` text word for word is flagged as the letter's `_repeats_resume` flags it.
- [X] T011 [US1] Implement `build_profile(...)` in `jobagent/core/generate.py`: load `PROFILE_PROMPT` with the T002 placeholders (`long_profile_rules` from `load_prompt("long_profile_rules")`, `on_page` rendered as `- [key] text` lines or "(none)"), append `instructions` then `feedback`, and call `_write_cited(client, prompt, PROFILE_PROMPT, profile, known=known_citations(profile, excluded), max_words=max_words, context="The PROFILE section", ad_text=jd.raw_text, on_resume=on_page)`; excluded ids from `kinds.excluded_ids(profile, kinds.kinds_of(kind), jd)` as the letter does. Add a third-person check on each paragraph (`check_third_person(..., name=False, pronouns=True)`) through the `recheck` callable so repairs are re-checked too.
- [X] T012 [US1] Factor the cover letter's claim-check → `_repair` → one rewrite → re-check block in `jobagent/services/documents.py` into a helper `_checked_text(write, *, check_claims, config, ctx, profile, review_client, document) -> tuple[GeneratedText, claims_found, rewrites]`, where `write(feedback)` builds the text; switch the letter to it with no behaviour change (existing letter tests must pass unchanged).
- [X] T013 [US1] Tests first in `tests/test_cli_generate.py` (or a new `tests/test_agency_resume.py`) through `services.documents.generate(..., resume_kind=ResumeKind.master_profile, master=None)` with mocks: the suggested master is the base; the file is `docs.document_name("Resume", jd, when=today)` (no master id in the name); only PROFILE differs from the master; the plain master file is not copied; the resume record has `base` = the master id and `long_profile` = true; a job that is "not a target" with no master named raises a typed refusal before any client is built; a master whose PROFILE heading is missing raises a typed refusal before any client is built.
- [X] T014 [US1] Implement the `master_profile` path in `services.documents.generate` and `plan`: new keyword `resume_kind: ResumeKind | None = None` (None keeps today's `resume`/`master` arguments working); resolve the base master (named, else suggested; else `NoMasterForProfile` refusal, new in `jobagent/services/refusals.py`); before any spend, verify the PROFILE heading by calling `replace_profile` into a temp file with the master's own text (refusal `MasterProfileMissing` on `DocxError`); after spend starts, `_checked_text(lambda fb: build_profile(...))`, write with `replace_profile` to `path_for_write(..., _name("Resume", …, blocked=…))`, `_keep_generated`, put `rendered["resume"]` and `per_document["resume"]`, and pass `base`/`long_profile` to `_records`. `planned_names` lists the resume name and not the master file for this kind.
- [X] T015 [US1] Page limit for the master copy (research R4): after writing, `count_pages(path)`; over `FULL_TIME_LENGTH.limit` → one `build_profile` rewrite with feedback "The resume renders at {pages:.2f} pages; the limit is 3. Cut the PROFILE to at most {target} words." where `target = max(80, words_now - ceil((pages - 3.0) * PAGE_LINES * LINE_WORDS) - 10)`, `PAGE_LINES = 46`, `LINE_WORDS = 12` (constants with a comment citing the 2026-11-25 measurement); rewrite the file, re-measure; still over → `length_issue` blocker and the `_NOT-READY` name (rename the written file). None from `count_pages` → no check, and `resume_pages` stays None. Tests with `count_pages` monkeypatched to 3.2 then 2.9, and 3.2 twice.
- [X] T016 [US1] CLI `--long-profile` in `jobagent/cli/generate.py` per `contracts/cli.md`: alone implies `--resume`; with `--master <id>` that master. (`--custom` / `--no-master` with `--long-profile` are wired in T022; nothing is merged to `main` before T022 is done.) Print the base before spending ("Resume: copy of the <label> master with a longer profile"), the cost line from `costs.estimate(..., profile=True)`, and after the run the profile's word count and pages. Tests in `tests/test_cli_generate.py`.
- [X] T017 [US1] `assessment.md`: the **Resume:** line says "copy of the <label> master with a longer profile" for this kind, in `jobagent/adapters/docs.py` `assessment_markdown` (new optional argument `resume_kind`). Test in `tests/test_docs.py`.

**Checkpoint**: US1 works from the CLI, end to end with mocks.

---

## Phase 4: User Story 2 - Held to the profile's evidence (P1)

**Goal**: prove the longer profile gets every PROFILE guard. Mostly tests: the machinery is the letter's and the resume's.

**Independent test**: each bad profile below is caught, and a surviving blocker names the file `_NOT-READY`.

- [X] T018 [P] [US2] Tests in `tests/test_agency_resume.py`, each through `services.documents.generate(resume_kind=master_profile)` with mocks: a sentence citing an entry marked `never_in_documents` in `profile.example/` (add one invented entry to the example profile if none exists) is a blocker and is not on the page after repair fails; a banned phrase from the example `voice.md` is a blocker; a figure absent from the haystack is flagged by the number check; an em-dash is a warning; a claim-check mismatch is repaired alone on the repair route (`_repair`), and a failed repair leads to one full rewrite with `claims_feedback`; `--no-check-claims` skips the check and the result says so.
- [X] T019 [US2] Fix whatever T018 finds missing in `build_profile`'s `recheck` or `_checked_text` (expected: nothing, or the third-person check on repaired sentences); if nothing, record "no change needed" against this task.

---

## Phase 5: User Story 3 - A custom resume with a longer profile (P2)

**Goal**: `generate <id> --custom --long-profile` (and the UI's `custom_profile`) makes a custom resume whose PROFILE is up to 250 words, in one resume call.

**Independent test**: with mocks, PROFILE within 250 words passes, over 250 is a blocker, and the rest of the resume is as a normal custom resume.

- [X] T020 [P] [US3] Tests first in `tests/test_generate.py`: `build_resume(..., long_profile=True)` sends a prompt containing the `long_profile_rules` text and not `SHORT_PROFILE_RULE`; PROFILE paragraphs totalling 251 words give a blocker `rule="PROFILE length"`; 250 pass; `long_profile=False` behaves exactly as before.
- [X] T021 [US3] Implement `long_profile: bool = False` on `build_resume` and `_ask_for_selection` in `jobagent/core/generate.py` (`profile_rule` = `load_prompt("long_profile_rules")` when true, else `SHORT_PROFILE_RULE`), and the 250-word blocker in `_check_resume` (and in `apply_resume_repairs`, so a repaired paragraph is re-counted).
- [X] T022 [US3] `custom_profile` in `services.documents.generate`: `select()` passes `long_profile=True`; `length_feedback` gains a sentence naming the PROFILE as the first thing to shorten when `long_profile` (research R4: still one reselection); the record gets `base="custom"`, `long_profile=True`. CLI `--custom --long-profile` and `--no-master --long-profile` map here. Tests in `tests/test_agency_resume.py`.

---

## Phase 6: User Story 4 - What went is recorded (P1)

**Goal**: an application records the base and whether the longer profile went.

**Independent test**: `apply` on an invented Northwind Freight job with each route in research R5 records the expected pair; `status` shows `em+profile`.

- [X] T023 [P] [US4] Schema v20 in `jobagent/core/store.py`: `SCHEMA_VERSION = 20`; `("resume_long_profile", "INTEGER")` under `applications` in `_ADDED_COLUMNS` with a `# v20` comment; add the column to the `CREATE TABLE applications`; write and read it in the upsert and row mapping (NULL ↔ None, 1 ↔ True, 0 ↔ False). Test: a v19 database opens, gains the column, old rows read None.
- [X] T024 [US4] `SentResume.long_profile: bool | None` and the rules of research R5 in `resolve_sent` (`jobagent/services/masters.py`): new argument `long_profile: bool = False` (only with `chosen`); `chosen == "custom"` plus flag → custom+profile; `sent_as_generated` → `latest_resume_kind` (T006) else custom; a sent file identical to a master → that master, flag False; any other sent file → `latest_resume_kind` when present, else custom; nothing named → suggested master, flag False. Tests in `tests/test_masters.py` for each row.
- [X] T025 [US4] Pass the flag through `jobagent/services/pipeline.py` (`resume_long_profile` beside `resume_master`) and `apply` in `jobagent/cli/apply.py`: `--long-profile` per `contracts/cli.md`, refused (exit 2) without `--master`, `--sent-resume` or `--sent-as-generated`; the confirmation line says "… master with a longer profile"; `status`'s `resume` column shows `<id>+profile` / `custom+profile`. Tests in `tests/test_cli_apply.py`.

---

## Phase 7: User Story 5 - Choosing it in the UI (P1)

**Goal**: the Generate panel offers the four kinds as one choice; the Pipeline form records the variants.

**Independent test**: posting the Generate form with `resume_kind=master_profile` and no cover letter reaches `services.documents.generate` with that kind (mocked), and the confirmation page shows the `generate_profile` cost line.

- [X] T026 [US5] `_generate_choice` in `jobagent/web/routes.py`: read `resume_kind` (`none|master|master_profile|custom|custom_profile`; anything else refused with a message) and the `master` select; map to `services.documents.plan/generate(resume_kind=…, master=…)`; keep accepting the old `use_master`/`resume` fields for one release only if a test or bookmark depends on them (check `tests/test_web*.py`; otherwise remove). Confirmation (`_generate_confirm`) passes `profile=True` to the cost estimate for `master_profile`. Tests in the existing web test file.
- [X] T027 [US5] `jobagent/web/templates/detail.html` Generate panel per `contracts/ui.md`: the radio group with the defaults stated there, the master select applying to both master values, master values hidden when there are no masters; a few lines of inline vanilla JS (no library, no CDN) untick the cover-letter box when a `*_profile` value is chosen. `generate_confirm.html`: the resume line names the base and "with a longer profile". Bump the static version string if a static file changes.
- [X] T028 [US5] Pipeline form in `detail.html` and the apply route in `routes.py`: add `<id>+profile` options per master and `custom+profile`; parse the suffix into `long_profile`; pass to `resolve_sent`. The "Resume sent" line shows "<label> master with a longer profile" / "a custom resume with a longer profile". Tests in the web test file.

**Checkpoint**: restart `jobagent ui` and click through with the demo workspace (`jobagent ui --demo`), which uses invented data.

---

## Phase 8: Polish & cross-cutting

- [X] T029 [P] `revise --resume` refusal in `jobagent/services/revise.py` (research R8): when `latest_resume_kind` has a master base, raise a typed refusal; word it in `jobagent/cli/revise.py` and the UI per `contracts/cli.md`. Test.
- [ ] T030 [P] `docs/decisions.md`: add D53 (research R10), and link it from D51.
- [ ] T031 [P] `CLAUDE.md`: under *Master resumes*, one paragraph on the longer-profile variant, the 250-word cap, the record, and D53; add D53 to *Design invariants* as one line. `README.md`: the loop for an agency ad (`generate <id> --long-profile`, the UI choice, `apply --long-profile`), with what it costs read from `jobagent spend` after the first runs, never quoted from memory.
- [ ] T032 Full suite; `git diff main --stat` and a read of the whole diff for real names, figures or profile text (Constitution VI) before the merge.
- [ ] T033 By hand, paid, once (quickstart "By hand"): state the expected cost first; run on one real agency ad with each master that fits; record the page counts in spec SC-003 (as numbers only, no employer names) and the cost comparison for SC-004.

---

## Dependencies

- Phase 1 → Phase 2 → US1 (T007-T017).
- US2 (T018-T019) needs US1.
- US3 (T020-T022) needs T003, T004, T005, T006; independent of US1 except the CLI flag (T016), whose `--custom` combination is wired in T022.
- US4 (T023-T025) needs T004 and T006; independent of US1-US3 in code, but its tests use records that US1 writes, so build it after US1.
- US5 (T026-T028) needs US1, US3 and US4 (it offers all four kinds and records them).
- Polish after all stories; T033 last.

## Parallel opportunities

- T001, T002 together; T004, T005 together.
- In US1: T007 (adapter tests) beside T010 (core tests).
- T020 (US3 tests) and T023 (schema) can be written beside US1's later tasks.
- T029, T030, T031 together.

## Implementation strategy

1. **MVP = US1 + US2**: the master copy with a longer profile from the CLI,
   checked and measured. Usable for agency ads at once, recorded by hand with
   a note until US4.
2. US3 (custom with longer profile), then US4 (recording), then US5 (UI).
3. Polish, then the one paid run.
