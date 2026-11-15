---
description: "Task list for 004 master resumes (as built)"
---

# Tasks: Master Resumes

**Input**: `specs/004-master-resumes/` (spec.md, plan.md, research.md,
data-model.md, quickstart.md)

**As built**: T001–T016 were done before this file existed; each names its
commit. T017 is open and goes through the normal plan/tasks flow.

**Tests**: written before the code in every commit. No model is called by
this feature.

**Examples**: invented only (Constitution VI).

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Registry (US1)

- [X] T001 [US1] `MasterEntry`, `MastersFile`, `MasterResume` in `jobagent/core/models.py`; `load_masters()` in `jobagent/core/masters.py` (optional file, one default, unique ids, files exist, .docx/.pdf extensions); `profile validate` lists the masters (`fdf9a9f`).

## Phase 2: Selection (US2)

- [X] T002 [US2] `title_shape()`, `select_master()`, `MasterChoice`; parametrised tests over invented titles (`dae487c`).
- [X] T003 [US2] Lead-engineer titles read as hands-on; team lead at manager seniority stays a lead; AI adoption read from the title when unclassified; delivery checked before lead (`dae487c`).

## Phase 3: Display (US3)

- [X] T004 [US3] `services/masters.choose()`, broken registry reported as a choice; `describe_choice()`; `masters_profile()` seed in `tests/ui_seed.py` (`f9d0688`).
- [X] T005 [US3] `ScoreResult.master`; `score` / `score --last` "resume" row with the custom-resume route (`d4919c2`).
- [X] T006 [US3] `assessment.md` **Resume:** line; `AdDetail.master`; the job's page "Resume:" line (`3a0391a`).

## Phase 4: Record (US4)

- [X] T007 [US4] Schema v19: `applications.resume_master`, `resume_suggested`; model fields; upgrade test from v18 (`360acc4`).
- [X] T008 [US4] `resolve_sent()` and `SentResume`; `UnknownMaster` refusal; byte-identical copy is that master; repeat apply leaves a record alone (`bd5c60f`).
- [X] T009 [US4] `apply --master <id|custom>`, the suggestion assumed and said; `status` resume column (`bd5c60f`).
- [X] T010 [US4] UI Pipeline form "Master resume sent" choice, suggested marked; master file kept as sent; nothing assumed; recorded resume shown (`f64ffbe`).

## Phase 5: Never in documents (US5)

- [X] T011 [US5] `never_in_documents` on `Story` and `Bullet`; `excluded_ids` honours it with or without kinds; linked bullets follow (`a106b51`).

## Phase 6: Documentation

- [X] T012 [P] README: Master resumes section, generate for the letter, `apply --master`, status column, `profile/resumes/` (`9c726e9`).
- [X] T013 [P] `docs/decisions.md` D51 (pick, don't compose; code not model) and D52 (`never_in_documents`) (`9c726e9`).
- [X] T014 CLAUDE.md: master resumes section; format corrections from the v4 master; architecture; invariants (`52fda32`).
- [X] T015 Invented team name in a selection test (`22b69ea`).
- [X] T016 This spec, written as built.

## Phase 7: Open

- [ ] T017 [US6] Custom resume in the masters' layout: in `jobagent/adapters/docx_writer.py`, highlight labels as bold `Label:` with no em-dash, and CORE SKILLS as six bold-label paragraphs instead of the 4×2 table; tests in `tests/test_docx_writer.py` for both; confirm `adapters/pages.py` page counts and the number check still pass on the new layout. Plan first: decide whether the skills order per master applies to a custom resume.
