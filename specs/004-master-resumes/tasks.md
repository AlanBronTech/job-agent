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

## Phase 7: A custom resume in the masters' layout (US6, US7)

Planned 2026-11-16 before any code. Measured from the Engineering Manager
master: highlight label bold "Label: " then the claim; CORE SKILLS lines in
Normal style, 10.5pt, 1pt before / 2pt after, bold "Label: " then the list;
EARLIER CAREER "**Name (years)**: summary"; certifications "Name (Issuer)",
degrees "Qualification, Institution".

- [ ] T017 This plan: clarifications, FR-012-FR-014, US7, tasks T018-T022.
- [ ] T018 [US6] Renderer and assembly in the masters' layout: `_bullet_with_label` and the EARLIER CAREER split use ": "; `_skills_lines` replaces `_skills_table`; `_assemble` builds earlier-career and founder lines with ": ", education as "Name (Issuer)" / "Qualification, Institution", skills joined with "; " and labelled in sentence case ("AI", "Cloud and data"); the highlight repair key and `resume_text` use ": ". Tests first in `tests/test_docx_writer.py` and `tests/test_generate*.py`; `docx_reader` still reads the new layout.
- [ ] T019 [US7] `_check_em_dashes` in `jobagent/core/validation.py`: a warning per em-dash, from `validate_prose` and `validate_rendered`, naming the text. Tests in `tests/test_validation.py`.
- [ ] T020 [US6] `skills_order` on a master (`MasterEntry`, `MasterResume`); `profile validate` refuses a key the profile's skills lack; `build_resume(skills_order=…)` uses it over the role-kind order and lists every category it names; `services/documents` passes the chosen master's order. Tests first.
- [ ] T021 Profile (gitignored, diff shown first): `roles.yaml` `skills` become the master's six categories, text verbatim; `masters.yaml` gains each master's `skills_order`; `profile validate` passes.
- [ ] T022 CLAUDE.md Document format: the new layout, the "not yet done" note removed; README if it describes the old layout.
