---
description: "Task list for the reapplication rule and batch review"
---

# Tasks: Reapplication Rule and Batch Review

**Input**: `specs/002-reapplication-batch/` — plan.md, spec.md, research.md,
data-model.md, contracts/, quickstart.md

**Tests**: required (Constitution IV; quickstart.md names the test per
requirement). Model calls are always mocked.

**Standing rules** (as in 001): `services/` never imports `typer`, `rich`,
`jobagent.cli` or `get_config`; CLI modules keep calling their own
`get_config()` so the existing `test_cli_*` suites pass unchanged; test data
is invented (Fabrikam Medical, Northwind Freight, `JR_000123`); one commit per
task; run `uv run pytest -q` before each commit; scan the diff for real names
before committing (Constitution VI).

**Order**: both P1 stories are built before the P2 ones. The rule (US2) comes
first because it is smaller and is what saves money. Its tests set
`requisition_id` and outside applications directly, so it does not wait on
US3 or US4.

---

## Phase 1: Setup

- [X] T001 Branch check: `002-reapplication-batch` is based on `001-local-ui` and `uv run pytest -q` passes. Starting count recorded 2026-10-04: **734 passed**.

---

## Phase 2: Foundational (blocks every story)

- [ ] T002 Add to `jobagent/core/models.py`: `JobDescription.requisition_id: str | None = None` and `JobDescription.source_file: str | None = None`; a new model `OutsideApplication(id, company, title, requisition_id, applied_on: date, channel, status: ApplicationStatus, notes, linked_jd_id, created_at)`; a new model `ReapplyDecision(jd_id, decision: Literal["same","different","overrule"], matched: str, decided_at)`; and `TargetFilters.reapply_window_days: int | None = 183` with a comment saying null turns the rule off (Alan, 2026-10-03).
- [ ] T003 Schema v10 in `jobagent/core/store.py`: bump `SCHEMA_VERSION` to 10; add `requisition_id TEXT` and `source_file TEXT` to `job_descriptions` through `_ADDED_COLUMNS`; create `outside_applications` exactly as data-model.md (`applied_on` "NOT NULL", `status` "NOT NULL", `notes` "NOT NULL DEFAULT ''", `linked_jd_id` "→ job_descriptions(id) ON DELETE SET NULL") and `reapply_decisions` (`jd_id` "INTEGER PK → job_descriptions(id) ON DELETE CASCADE", "One decision per ad"); read and write the new JD columns in `add_jd`, `update_jd` and `_row_to_jd`; add `add_outside`, `list_outside`, `get_outside`, `link_outside`, `get_reapply_decision` and `set_reapply_decision`. Tests in `tests/test_store.py`: a v9 database migrates and keeps its rows; cascade and set-null behave.
- [ ] T004 [P] Create `jobagent/core/requisition.py` with `extract_requisition(text) -> str | None` and `normalise_requisition(value) -> str`, per research R1: Workday `JR[_-]?\d{4,}`, plus labelled forms (requisition, req, job, reference, ref, vacancy, position, followed by id, no, number, # or code, then a separator); the value stored exactly as written; more than one distinct normalised value → `None`. Tests in `tests/test_requisition.py`: `JR_000123`, `Req ID: 45871`, `Job reference: ABC-2026-77`, none present, two different numbers, and the same number twice.
- [ ] T005 [P] Add `SameJobRecently(match)` and `PossiblySameJob(match)` to `jobagent/services/refusals.py`, carrying the match facts: kind, against (an application or an outside record), company, title, requisition id, applied_on, age_days.
- [ ] T006 [P] Add `reapply_window_days: 183` to `profile.example/assets.yaml`, with a comment. Then **stop and ask Alan** before adding it to his `profile/assets.yaml` (spec 002 plan: confirm the wording); record the date and his words in a YAML comment.
- [ ] T007 Create `jobagent/services/pipeline.py` with `outcome(ws, jd_id, status, *, worth=None, why="", note="")`, moved out of `jobagent/cli/apply.py`'s `_save` (no such ad → `NoSuchAd`; notes appended as now), and rewire `cli/apply.py`'s `outcome` to call it. `test_cli_apply.py` must pass unchanged. This is 001's T039 brought forward for this one function: mark that part done in `specs/001-local-ui/tasks.md` with a note. `batch skip` (CLI and UI) calls this, so recording `not_applied` adds no logic to `web/` or to another CLI module.

**Checkpoint**: suite passes; `jobagent profile validate` passes.

---

## Phase 3: User Story 2 — Don't reapply to the same job within six months (P1) 🎯

**Goal**: refuse before spending, with a recorded overrule or a recorded yes/no.
**Independent test**: an outside application to `JR_000123` 90 days ago; an ad with `requisition_id=JR_000123` → score and generate refuse with a booby-trapped client; an ad for `JR_000456` at the same company scores normally.

- [ ] T008 [US2] Create `jobagent/core/reapply.py` with `match(jd, applications, outside, window_days, today) -> Match | None`, per research R2: "same" on equal normalised requisition id, equal `source_url`, or a recorded `same` decision; "possibly_same" on `history.same_company` + equal normalised title (case and punctuation folded) + no requisition id on **either** side; differing ids → no match; only records with `applied_on`; window measured from `applied_on`; outcome ignored; linked outside rows not counted twice. Also a match against another *stored ad* with the same normalised requisition id that has been scored or applied for (spec edge case: two ads in one batch with the same number), so once one is scored the other is refused. Tests in `tests/test_reapply.py`, covering spec US2 scenarios 1–5 and the edge cases (window boundary at day 182 and 183, a withdrawn application still counts, different ids with the same title).
- [ ] T009 [US2] Create `jobagent/services/reapply.py`: `check(ws, jd_id, today) -> Clear | SameJob | PossiblySame` (reads profile `reapply_window_days`; `None` → always `Clear`; if the profile cannot be loaded, return `Clear` so the later `ProfileMissing` or `ProfileInvalid` refusal fires as it does today, and test that), applying recorded decisions (`overrule` → Clear; `different` → Clear; `same` → SameJob); `decide(ws, jd_id, decision, matched)`.
- [ ] T010 [US2] In `jobagent/services/scoring.py` and `jobagent/services/documents.py`, call `reapply.check` right after `NoSuchAd`/load and before every other refusal; raise `SameJobRecently` or `PossiblySameJob`. Add the reapply state to `documents.plan()`'s `GeneratePlan` (add a field to `jobagent/services/results.py`).
- [ ] T011 [US2] In the CLI, in `jobagent/cli/score.py` and `jobagent/cli/generate.py`, map the two refusals to the messages in contracts/cli.md (exit 2), and add `--overrule-reapply`, which records `overrule` and retries. Add `jobagent jd same <id> yes|no` to `jobagent/cli/jd.py`. Existing `test_cli_*` suites pass unchanged.
- [ ] T012 [US2] In the UI, `jobagent/web/templates/detail.html`, `score_confirm.html` and `generate_confirm.html` show the flag ("Same job you applied for on <date>, <n> days ago" / "Possibly the same job as …"), with buttons Same job / Different job / Overrule posting to `POST /ads/{id}/reapply` (new route in `jobagent/web/routes.py`; token required). With an unresolved flag there is no Confirm button.
- [ ] T013 [US2] Tests in `tests/test_services_reapply.py` and `tests/test_web_reapply.py`: SC-001 both ways (the id in the ad: refused; no id: asked, then `yes` → refused, `no` → scored), refusals raised with `get_client` booby-trapped, the overrule recorded and per-ad only (FR-009, spec assumption), a different job at the same company scores normally (SC-005), and window null → off.

**Checkpoint**: the worked example spends nothing.

---

## Phase 4: User Story 1 — Review a batch in one table (P1)

**Goal**: one row per saved file, including refused ones; score several; skip several.
**Independent test**: five invented files (one cut off at "…more", one duplicate of a stored ad) → five rows, three parsed, one refused with its reason, one flagged; score two; skip the rest.

- [ ] T014 [US1] In `jobagent/services/ads.py` `add()`, store `source_file` (a bare file name, or None for pasted text) and `requisition_id = extract_requisition(raw_text)` on the new ad. Test in `tests/test_services_ads_scoring.py`.
- [ ] T015 [US1] Create `jobagent/services/batches.py`: create the `batches(id, owner, started_at)` and `batch_rows(batch_id, file_name, jd_id NULL, refusal NULL, refusal_detail NULL)` tables on first use, as `services/runs.py` does; `new_files(ws)` (files in `AD_SUFFIXES` with no ad whose `source_file` matches, and mtime after the baseline: the `started_at` of the earliest row in this service's own `batches` table, so nothing batch-related is written to core's `meta`; with no batch yet, the baseline is now); `start(ws)`; `parse(ws, config, batch_id, *, client_factory=None, before_spend=None)` (for each row with neither a jd_id nor a refusal: `read_ad`, then a `CaptureTruncated` / `UnreadableAd` refusal is recorded with its reason and next step, or `ads.add`, with the jd_id recorded); a likely duplicate (identical `raw_text` already stored) recorded as refusal `duplicate` with the existing JD id; `rows(ws, batch_id, today)` returning the derived row (data-model "Batch row"), including hard filters from `scoring.check_constraints` (free) and `reapply.check`; two rows in one batch with the same normalised requisition id are both flagged "same requisition as row N".
- [ ] T016 [US1] Tests in `tests/test_services_batches.py`: one row per file (SC-003), a refused capture as its own row, a duplicate flagged, resume after an interruption repeats no paid step (FR-007; count calls to the fake parser), the first run sets the baseline so older files are not offered, and two files with the same requisition id are both flagged, with only the first scorable without an overrule.
- [ ] T017 [US1] Create `jobagent/cli/batch.py` per contracts/cli.md: `jobagent batch` (free: current table or new files plus the parse cost), `batch parse`, `batch skip IDS` (calls `services.pipeline.outcome(..., not_applied)` for each, from T007). Register it in `jobagent/cli/main.py`. Render the table with rich, refused rows included, with the reason and next step.
- [ ] T018 [US1] Make `jobagent score` accept several ids in `jobagent/cli/score.py`: the combined estimate, each scored in turn, refusals reported per ad without stopping the rest; exit 0 if any were scored, else 2. `--last` and `--json` keep their single-id behaviour (refuse more than one id). The existing tests pass unchanged.
- [ ] T019 [US1] Tests in `tests/test_cli_batch.py`: the table includes the refused row; `score 63 64 65` with one refused; `batch skip`.
- [ ] T020 [US1] Web: `GET /batch` and `templates/batch.html` (the same columns as the CLI; a checkbox per row; refused rows with their reason); `POST /batch/parse/confirm` and `/batch/parse` (one `add_ad` run per file through the runner); `POST /batch/score/confirm` and `/batch/score` (the combined cost; one `score` run per selected id; refused ids listed, not started); `POST /batch/skip` (calls `services.pipeline.outcome` for each selected id). Each row links to its ad page for generate. Add "Batch" to the nav in `base.html`. All POSTs use `checked_form`.
- [ ] T021 [US1] Tests in `tests/test_web_batch.py`: US1 acceptance scenarios 1–5; nothing starts without `confirmed=1`; the same rows as the CLI (FR-006, compared through the service); and parity (FR-005, SC-004): score one invented ad from a batch and an identical one singly, with the same mocked client, and assert the same stored assessment fields and the same run-log records, excluding `run_id`, `ts`, `jd_id` and `source`.

**Checkpoint**: a batch of seven goes from saved files to a scored table in two confirmations.

---

## Phase 5: User Story 3 — Outside applications (P2)

**Goal**: record and link applications made outside the tool.
**Independent test**: record Fabrikam Medical `JR_000123`, 2026-05-05, with no ad; add an ad carrying `JR_000123` → US2 fires; link the two → one pipeline record keeping 2026-05-05.

- [ ] T022 [US3] Create `jobagent/services/applications.py`: `record_outside(ws, *, company, title, requisition_id, applied_on, channel, status, notes)` (a future date → `BadDate`); `list_outside(ws)`; `link_outside(ws, outside_id, jd_id)` (sets `linked_jd_id`; creates or updates the ad's `applications` row with the outside `applied_on`, status and appended notes).
- [ ] T023 [US3] Make `jobagent/core/history.py` `company_history` include unlinked outside applications as encounters (marked "outside"). The reapply match (T008) already reads them.
- [ ] T024 [US3] CLI in `jobagent/cli/apply.py`: `apply --outside --company --title [--req] --on --channel [--status] [--note]`, `apply --outside-list`, and a new `jobagent link <outside_id> <jd_id>` command registered in `jobagent/cli/main.py`.
- [ ] T025 [US3] Tests in `tests/test_services_applications.py` and `tests/test_cli_apply.py`: US3 scenarios 1–4; a linked record is not counted twice in history or by the rule.

---

## Phase 6: User Story 4 — Requisition numbers (P2)

**Goal**: shown everywhere, and backfilled for stored ads.
**Independent test**: `jd backfill` over invented stored ads sets ids exactly, none when ambiguous, and spends nothing.

- [ ] T026 [US4] Add `backfill(ws) -> BackfillReport` to `jobagent/services/ads.py`: for every stored ad with no `requisition_id`, extract one from `raw_text`; for every ad with no `source_file`, match a saved file whose extracted text equals `raw_text` exactly (no model call); report the counts and the ambiguous ones. Add `jobagent jd backfill` to `jobagent/cli/jd.py`.
- [ ] T027 [US4] Show the requisition id in `jobagent jd show`, the `score` header, `assessment.md` (`jobagent/adapters/docs.py`), and the UI detail and list pages.
- [ ] T028 [US4] Tests in `tests/test_services_ads_scoring.py` and `tests/test_cli_jd.py`: backfill exactness, no model client built, ambiguous cases reported.

---

## Phase 7: Polish

- [ ] T029 Eval leakage (FR-015 and the live defect): `cases_from_applications` in `jobagent/core/evals.py` takes the ads' `ingested_at` and leaves out applications with `applied_on` before the ad's capture date; `jobagent/cli/evals.py` passes the dates and `eval report` prints "N case(s) left out: the ad was captured after the application". Tests in `tests/test_evals.py`.
- [ ] T030 [P] Update `README.md` (batch, the six-month rule, outside applications, `jd same`, `jd backfill`) and `CLAUDE.md` (the commands table, an invariant for the six-month rule as a pre-spend refusal and why it is not a hard filter, and the eval leakage exclusion).
- [ ] T031 Run `jobagent jd backfill` against the real store (free). Report the counts to Alan, and ask whether to record any outside applications he remembers.
- [ ] T032 Replay the worked example per quickstart.md (≈ $0.04). **Ask Alan before running.**
- [ ] T033 Before the final commit, scan `git diff 001-local-ui` for real names and requisition numbers (Constitution VI).

---

## Dependencies

```text
Setup (T001) → Foundational (T002–T007)
  ├─► US2 (T008–T013)     tests set requisition_id and outside rows directly
  ├─► US1 (T014–T021)     uses US2's check for the flag column (T009)
  ├─► US3 (T022–T025)     T023 needs T003
  └─► US4 (T026–T028)     T026 needs T004
Polish (T029–T033)
```

Inside US1: T014 → T015 → T016 → T017/T018 → T019 → T020 → T021.

## Parallel opportunities

- Foundational: T004, T005, T006 and T007, once T002/T003 are done.
- After US2: US3 (T022–T025) and US4 (T026–T028) touch different files from US1 and can run alongside it.
- Polish: T030.

## Implementation strategy

1. **Increment 1: the rule (T001–T013).** It stops the money being spent. It
   works on its own with outside applications recorded by hand.
2. **Increment 2: the batch (T014–T021).** This is the weekly loop.
3. **Increments 3 and 4: outside applications and requisition backfill.** They
   make the rule see history from before the tool existed.
4. **Polish**, including the eval fix, which is independent and could go first
   if the eval set is about to be used.

Total: 33 tasks.
