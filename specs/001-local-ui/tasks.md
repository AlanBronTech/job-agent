---
description: "Task list for the Phase 8 local UI"
---

# Tasks: Local UI (Phase 8)

**Input**: `specs/001-local-ui/` — plan.md, spec.md, research.md, data-model.md,
contracts/, quickstart.md

**Tests**: required. Constitution IV says every task that changes behaviour ends
with the full suite passing, and quickstart.md names the test that proves each
requirement. Baseline at the start: **562 passing**. Model calls are always
mocked; nothing here touches the network.

**Standing rules for every task**

- `jobagent/services/` never imports `typer`, `rich`, `jobagent.cli` or
  `jobagent.config.get_config`, and never prints or exits. Refusals are typed
  exceptions carrying facts; wording belongs to the caller.
- When a workflow moves out of a CLI module, that module **keeps calling its own
  `get_config()`** and builds `Workspace.from_config(config)` from it. The
  existing `test_cli_*` suites monkeypatch `<cli_module>.get_config`; they must
  pass **unchanged**, because they are the parity net for the move. Existing
  messages and exit codes do not change.
- Test data is invented (Acme Logistics, Northwind Freight). Constitution VI:
  scan the diff for real names and figures before each commit.
- One commit per task, or per tightly coupled pair. Run `uv run pytest -q` before
  each commit.

## Format: `[ID] [P?] [Story] Description`

**[P]**: can run in parallel (different files, no dependency on an incomplete task).

---

## Phase 1: Setup

- [ ] T001 Add `fastapi`, `uvicorn`, `jinja2`, `python-multipart` to `dependencies` in `pyproject.toml`, with a one-line comment giving the reason (research R2). Run `uv sync` and `uv run pytest -q` (562 pass).
- [ ] T002 [P] Create empty packages `jobagent/services/__init__.py` and `jobagent/web/__init__.py`, plus directories `jobagent/web/templates/` and `jobagent/web/static/`. Confirm `uv build` includes non-Python files under `jobagent/web/`, and add a hatch `include` in `pyproject.toml` if it does not.
- [ ] T003 [P] Vendor HTMX 2.x minified into `jobagent/web/static/htmx.min.js`. Record its version, source URL and BSD-2 licence in `jobagent/web/static/README.md`. No page may reference a CDN.
- [ ] T004 [P] Update the Architecture section of `CLAUDE.md`: add `services/` (workflow orchestration shared by `cli/` and `web/`, with the rules above) and `web/` (routes and templates only, calling `services/`). Note the decision date, 2026-09-29.

---

## Phase 2: Foundational (blocks every story)

- [ ] T005 [P] Create `jobagent/services/workspace.py`: a frozen dataclass `Workspace(owner: str, profile_dir: Path | None, db_path: Path, runs_log_path: Path, jd_dir: Path, documents: DocumentStore)` and `Workspace.from_config(config) -> Workspace` with `owner="local"` and `documents=LocalFolderStore(config.output_dir)`. Tests in `tests/test_workspace.py`.
- [ ] T006 [P] Create `jobagent/services/refusals.py`: base `Refusal(Exception)` and the refusals in data-model §6 (`NoSuchAd`, `NotScored`, `NothingSelected`, `VerdictIsSkip(rationale)`, `ThinAd(chars)`, `CaptureTruncated`, `UnreadableAd(detail)`, `AlreadyGenerated(folder, files)` where files are `(name, mtime)`, `SupersedeFailed(folder, reason)`, `ProfileMissing`, `ProfileInvalid(detail)`, `NoModel(detail)`, `BadDate(detail)`, `RunInProgress(run_id)`, `AdNotFound(detail)`). Create `jobagent/services/results.py` with `AddResult`, `ScoreResult`, `GeneratePlan`, `GenerateResult`, `PrepResult` as dataclasses whose fields follow data-model §6.
- [ ] T007 Move `_folders_for` from `jobagent/cli/jd.py` to `jobagent/adapters/docs.py` as public `folders_for(output_dir, jd) -> list[Path]`, with the docstring kept. `cli/jd.py` calls it. `tests/test_cli_jd_delete.py` passes unchanged.
- [ ] T008 Add `supersede_folder(folder: Path, now: datetime) -> Path` and `is_superseded(folder: Path) -> bool` to `jobagent/adapters/docs.py`. Name format, verbatim from data-model §2: "`<YYYY-MM>.superseded-<YYYYMMDDTHHMMSS>_<suffix>`. The part before the first `_` contains no underscore". Implemented as one `os.rename`. Raise `DocsError` if the target exists or the rename fails, leaving the folder untouched. Tests in `tests/test_docs_supersede.py`: name format; `folders_for` finds the superseded folder; a pre-existing target and a read-only parent both leave the original byte-for-byte intact.
- [ ] T009 [P] Create `jobagent/adapters/desktop.py`: `open_file(path, *, root, run=subprocess.run)` → `["open", str(path)]` and `reveal(path, *, root, run=...)` → `["open", "-R", str(path)]`. Refuse with `ValueError` any path whose `resolve()` is not inside `root.resolve()`. Tests in `tests/test_desktop.py` with a fake `run` and a symlink-escape case.
- [ ] T010 Create `jobagent/adapters/document_store.py`: a `DocumentStore` Protocol (`folder_state(jd, when)`, `path_for_write(jd, when, name) -> Path`, `write_text(jd, when, name, text)`, `supersede(jd, when, now) -> str | None`, `list_for(jd) -> OutputFolders`, `open(jd, folder, name)`, `reveal(jd, folder)`), and `LocalFolderStore(output_dir)` implementing it over `docs.py` and `desktop.py`. Documents are referred to by `(folder name, file name)`, never by a client-supplied path. `open` and `reveal` refuse any folder not returned by `list_for(jd)`. Put the `OutputFolders` dataclass here, following data-model §3 (`current`, `superseded`, `earlier`, `any`), where `any` is "True if any of the above holds a `.docx`". Tests in `tests/test_document_store.py`.
- [ ] T011 Add the `ui_runs` table to `jobagent/core/store.py` and bump `SCHEMA_VERSION` to 10. Columns are exactly those in data-model §1, including `owner TEXT NOT NULL DEFAULT 'local'` and `jd_id` "ON DELETE CASCADE". Add the partial unique index `ON ui_runs(jd_id) WHERE status = 'running'`. Add functions: `start_run(conn, *, owner, kind, jd_id, run_id, request) -> int`, which does the check-and-insert inside `BEGIN IMMEDIATE`, raises `RunActive(existing_id)` (a `StoreError`) if the same `jd_id` is `running`, and for `add_ad` keys on `request["filename"]`; `finish_run(conn, id, *, status, result=None, error=None)`; `get_run`; `active_run_for(conn, owner, jd_id)`; `last_run_for`; `unseen_finished(conn, owner)`; `mark_seen(conn, id)`; `mark_seen_for_jd(conn, owner, jd_id)`; and `interrupt_running(conn) -> int`. Tests in `tests/test_store_ui_runs.py`: a v9 database migrates; a double start is refused; cascade on JD delete; interrupt; seen.
- [ ] T012 [P] Add `expected_cost(records, labels, model) -> dict[str, tuple[float, int] | None]` to `jobagent/core/spend.py`, following research R5: successful records only, matching label and model, summed per `run_id`, then averaged across `run_id`s. Tests in `tests/test_spend.py`: a retried parse counts as one action; other models are ignored; no samples → `None`.
- [ ] T013 Create `jobagent/services/costs.py` with `estimate(ws, config, action, *, resume=False, cover=False, answers=False) -> CostEstimate`, following data-model §4. It maps actions to labels (`add_ad`→`parse_jd`, `score`→`score_fit`, `prep`→`interview_prep`, `generate`→`generate_resume`/`generate_cover_letter`/`generate_answers` as selected), resolves the model with `adapters.llm.resolve_route`, sets `budget` from `config.budget_mode`, and reads `ws.runs_log_path` with `core.spend.load_runs`. A missing log gives no samples, not an error. Tests in `tests/test_costs.py`.
- [ ] T014 [P] In `jobagent/adapters/llm.py`, extend the `RunContext.source` comment to list `"ui"`. Add a test to `tests/test_spend.py` that a `source: "ui"` record appears as its own `by_source` row.
- [ ] T015 Create `jobagent/web/app.py`: `create_app(*, workspace_factory, config, runner, port, token) -> FastAPI`. Include middleware that returns 403 unless `Host` is `127.0.0.1:<port>` or `localhost:<port>`. For CSRF: `GET /?t=<token>` sets cookie `jobagent_csrf` (`HttpOnly`, `SameSite=Strict`), and every POST must carry a form field `csrf` equal to the cookie, otherwise 403. Set up the Jinja2 environment for `jobagent/web/templates/` with autoescape on, and mount `/static`. Tests in `tests/test_web_security.py`: wrong Host → 403; POST without a token or with a mismatched one → 403; a good request → 200.
- [ ] T016 Create `jobagent/web/runner.py`: `Runner(workspace, max_workers=2)` over a `ThreadPoolExecutor`. `start(kind, jd_id, request, fn) -> run id` inserts via `store.start_run`, then runs `fn` in a worker and calls `finish_run` with `succeeded` and the JSON result, or with `failed` and the refusal or error text. Each worker opens its own connection. `SyncRunner` does the same synchronously for tests. Tests in `tests/test_web_runner.py`: two concurrent starts for one ad → one run; a failure is recorded; a leftover `running` row becomes `interrupted` on `interrupt_running`.
- [ ] T017 Create `jobagent/web/templates/base.html` (nav: Ads, Board; `csrf` available to every form), `jobagent/web/templates/_banner.html`, `jobagent/web/templates/_run.html` and `jobagent/web/static/app.css`. The banner lists `unseen_finished` runs with ad and outcome. An `interrupted` run reads "interrupted when the UI stopped — its cost may be missing from `jobagent spend`". In `jobagent/web/routes.py`: `GET /runs/{id}` returns `_run.html` and polls every 2 s with `hx-trigger` only while `running`; `POST /runs/{id}/seen` marks it seen. Tests in `tests/test_web_runner.py`.
- [ ] T018 Create `jobagent/cli/ui.py` and register it as `ui` in `jobagent/cli/main.py`, following contracts/cli.md: `--port` (default 8765), `--no-browser`, bind `127.0.0.1` only with no `--host`. On a busy port, exit 2 with the message from the contract. Generate the token with `secrets.token_urlsafe`, call `interrupt_running` at start, open the browser with an injectable `webbrowser.open` after the server is listening, and require a second Ctrl-C while a run is `running`. It must work under `jobagent --budget ui`. Tests in `tests/test_cli_ui.py`, with the server and browser faked.

**Checkpoint**: 562 original tests plus the new ones pass. `jobagent ui` serves an empty base page.

---

## Phase 3: User Story 1 — Read the shortlist and an assessment (P1) 🎯 MVP part 1

**Goal**: list and detail pages, free and read-only.
**Independent test**: against a seeded store, list and detail match `jd list` / `score --last`, and no model client is constructed.

- [ ] T019 [P] [US1] Create `jobagent/services/outputs.py`: `documents_for(ws, jd) -> OutputFolders` via `ws.documents.list_for`, and `index_all(ws, jds) -> dict[int, OutputFolders]`, built from **one** listing of the output folder (SC-002). Tests in `tests/test_services_outputs.py`, including superseded and earlier-month folders.
- [ ] T020 [US1] Create `jobagent/services/listing.py`: `ad_rows(ws, *, sort="date"|"score")` returns id, company, title, captured date, verdict, both scores and status, newest first by default. `ad_detail(ws, jd_id)` returns the jd, latest assessment, stale flag (`store.latest_assessment_stale`), company history (`core.history.company_history`), `OutputFolders`, application, and active or last run. It raises `NoSuchAd`. Tests in `tests/test_services_listing.py`.
- [ ] T021 [US1] Add `GET /` (`?sort=date|score`) to `jobagent/web/routes.py`, rendering `jobagent/web/templates/list.html` (FR-010).
- [ ] T022 [US1] Add `GET /ads/{jd_id}` rendering `jobagent/web/templates/detail.html` (FR-011). Hard filters show ✓ met / ✗ breach / "not stated" for `ConstraintStatus.unknown`, and are never styled as met. Any breach is shown as overriding the verdict. Requirements show met/partial/gap with evidence and note. Also: challenge points, questions to ask, company history as information only, a stale-assessment banner, documents grouped current/superseded/earlier, and status. Opening the page calls `mark_seen_for_jd`.
- [ ] T023 [US1] Add `POST /ads/{jd_id}/documents/open` and `/reveal` (form fields `folder`, `name`) to `jobagent/web/routes.py`, calling `ws.documents.open/reveal`: 204 on success, 404 for anything not in `documents_for`. Add Open/Reveal buttons to `detail.html` (FR-016c).
- [ ] T024 [US1] Tests in `tests/test_web_read.py`: US1 acceptance scenarios 1–4 (including a Northwind Freight `rejected_screen` history that leaves the verdict unchanged, and an amended ad flagged stale); patch `adapters.llm.get_client` to fail if called; open/reveal reject a forged folder; 100 seeded ads render `/` and one detail page in under 1 s each (SC-002).

**Checkpoint**: US1 usable on its own.

---

## Phase 4: User Story 2 — Generate documents from a button (P1) 🎯 MVP part 2

**Goal**: generate with every CLI guard, supersede instead of overwrite, and a cost shown first.
**Independent test**: with mocks, a UI generate writes the same files, issues, unused list and run-log records as the CLI.

- [ ] T025 [US2] Create `jobagent/services/documents.py` by extracting from `jobagent/cli/generate.py`: `plan(ws, jd_id, *, resume, cover, answers, when) -> GeneratePlan` (planned names from `_planned_documents`, clashes with mtimes, verdict, `needs_overrule`; free), and `generate(ws, ctx, jd_id, *, resume, cover, questions, overrule=False, supersede=False, overwrite=False, today, now) -> GenerateResult`. Invariants from contracts/services.md: every refusal happens before any client is built; `overrule` on a skip records `overrode_scorer` as `_record_override` does, and a store failure there never blocks the documents but becomes a result warning; `supersede` and `overwrite` are exclusive; with `supersede`, the move happens first and `SupersedeFailed` leaves the folder untouched; the write order is resume, letter, answers, `assessment.md`, `job-ad.md`, all through `ws.documents`. Rewire `cli/generate.py` to map results and refusals to its current messages and exit codes. `tests/test_cli_generate.py` passes unchanged.
- [ ] T026 [US2] Add `--supersede` to `jobagent/cli/generate.py` per contracts/cli.md: exit 2 if combined with `--overwrite`; print the new folder name; exit 1 with nothing spent if the rename fails; the "Already generated" message gains "…or pass --supersede to keep them under a dated name." Add tests to `tests/test_cli_generate.py`.
- [ ] T027 [P] [US2] Tests in `tests/test_services_documents.py`: each refusal is raised with a mock client that fails on any call; overrule sets `overrode_scorer`; supersede + a rename failure spends nothing; a clean run returns the unused list with ongoing ventures first; the files match the CLI's names.
- [ ] T028 [US2] Add `POST /ads/{jd_id}/generate/confirm` and `POST /ads/{jd_id}/generate` to `jobagent/web/routes.py`, with `jobagent/web/templates/generate_confirm.html`. The confirmation shows the document checkboxes, `costs.estimate` (or "no measurement for <model> yet", or "free tier" in budget mode), any clash files with modification times plus the notice that the folder will be moved to a dated name, and a skip-overrule checkbox that repeats the assessment's rationale. The start route refuses without `confirmed=1`, refuses a clash without `supersede=1`, returns the existing run if one is active, and otherwise calls `runner.start("generate", ...)` with `RunContext(command="generate", jd_id=..., source="ui")`. Application questions come from a textarea, one per line.
- [ ] T029 [US2] Render generate results in `jobagent/web/templates/_run.html` and `detail.html`: files written, with Open/Reveal; validation issues, with blockers first and the result labelled "not ready: blocker" when any exist (FR-009, US2 scenario 4); the unused-entry list, shown on clean runs too, ongoing ventures first; any superseded folder name.
- [ ] T030 [US2] Tests in `tests/test_web_generate.py`: US2 scenarios 1–5 with `SyncRunner` and mocked clients; POST without `confirmed` → no run and no client; clash without `supersede` → refused; a double POST → one run.

**Checkpoint**: the BUILD_PLAN exit criterion (shortlist → assessment → documents) holds without a command. This is the MVP.

---

## Phase 5: User Story 3 — Add and score an ad (P2)

**Goal**: ad intake and scoring from the browser.
**Independent test**: an invented Acme Logistics ad added by file, by newest and by paste gives the same stored record and log records as `jd add`; score matches `score`.

- [ ] T031 [US3] Move `AD_SUFFIXES`, `AdNotFound`, `ads_in`, `latest_ad` and `resolve_ad` from `jobagent/cli/paths.py` into `jobagent/services/ads.py`. Keep `expand` in `cli/paths.py` (it is a typer callback), and re-export the moved names from `cli/paths.py` so existing imports and tests keep working.
- [ ] T032 [US3] Extract `add(ws, ctx, *, file=None, text=None, source=None) -> AddResult` into `jobagent/services/ads.py` from `jobagent/cli/jd.py:add` and `_extract_saved_page`: saved-page unwrapping; `CaptureTruncated` before any spend; a thin-capture warning in the result; parse; store; `log_attribution(ws.runs_log_path, ctx.run_id, jd_id)`; company history. `$EDITOR` input stays in the CLI. Rewire `cli/jd.py:add`; `tests/test_cli_jd.py` passes unchanged.
- [ ] T033 [US3] Create `jobagent/services/scoring.py` with `score(ws, ctx, jd_id, *, force=False) -> ScoreResult`, extracted from `jobagent/cli/score.py`: `NoSuchAd`, `ThinAd(chars)` unless `force`, `ProfileMissing`, `ProfileInvalid`, `NoModel`, all before spend. A store failure after scoring becomes a result warning, matching "Scored, but could not save". Rewire `cli/score.py`, keeping `--last` and `--json` there. `tests/test_cli_score.py` passes unchanged.
- [ ] T034 [P] [US3] Tests in `tests/test_services_ads.py` and `tests/test_services_scoring.py`: refusals before spend; attribution record written; thin warning.
- [ ] T035 [US3] Add `POST /ads/new/confirm` and `POST /ads/new` to `jobagent/web/routes.py`, with `jobagent/web/templates/add.html`: a file input that accepts dropped files, a "newest saved ad" button naming the file, and a paste textarea. A dropped file is written into `ws.jd_dir` under its own name: an identical file is reused, a different file with the same name is refused, and a suffix outside `AD_SUFFIXES` is refused before any cost, naming the accepted types. The confirmation names the file and shows the parse estimate. The run uses `RunContext(command="jd add", source="ui")`. On success, redirect to `/ads/{new id}`, where company history is shown.
- [ ] T036 [US3] Add `POST /ads/{jd_id}/score/confirm` and `/score` to `jobagent/web/routes.py`, with `jobagent/web/templates/score_confirm.html`: the cost; for a thin ad, the character count and a `force` checkbox; `RunContext(command="score", source="ui")`.
- [ ] T037 [US3] Tests in `tests/test_web_add_score.py`: US3 scenarios 1–3; an unsupported suffix → no client; a same-name different-content upload refused; a truncated capture refused with no spend.

---

## Phase 6: User Story 4 — Pipeline board and status changes (P3)

**Goal**: a board with every status, and status recording.
**Independent test**: record `applied`, then `rejected_after_interview`, for an invented ad; `jobagent status` shows the same.

- [ ] T038 [US4] Create `jobagent/services/pipeline.py` by extracting `apply` and `outcome` from `jobagent/cli/apply.py`, including the `_parse_date` rules (no future date; a repost cannot postdate the application) as `BadDate`. Add `board(ws) -> Board`, grouping ads under **every** `ApplicationStatus` value plus "documents generated, not recorded" (`OutputFolders.any` and no application row, or status `identified`). Rewire `cli/apply.py`; `tests/test_cli_apply.py` passes unchanged.
- [ ] T039 [US4] Add `GET /board` rendering `jobagent/web/templates/board.html`, and `POST /ads/{jd_id}/status` in `jobagent/web/routes.py`. The status is a select built from `ApplicationStatus` only; also collect dates, channel, reposted-on, worth, why and note. Add the status form to `detail.html`.
- [ ] T040 [US4] Tests in `tests/test_web_board.py`: US4 scenarios 1–2; an unknown status value is refused; a future date is refused.

---

## Phase 7: User Story 5 — Interview prep from a button (P3)

**Goal**: prep with the cost shown first, surviving a closed tab.
**Independent test**: with mocks, the prep file and content match `jobagent prep`.

- [ ] T041 [US5] Create `jobagent/services/prep.py` with `prepare(ws, ctx, jd_id, *, interviewers=(), save=True) -> PrepResult`, extracted from `jobagent/cli/prep.py`. Move `_markdown` into `jobagent/services/prep.py` as `prep_markdown`, and write `interview-prep.md` through `ws.documents.write_text`. Rewire `cli/prep.py`; the existing prep tests pass unchanged.
- [ ] T042 [US5] Add `POST /ads/{jd_id}/prep/confirm` and `/prep` to `jobagent/web/routes.py` (interviewers field, one per line, and the cost), with `jobagent/web/templates/prep_confirm.html`. Render the result in `_run.html`: opening, "The hard ones", "Also likely", "Ask them", and validation issues. `RunContext(command="prep", source="ui")`.
- [ ] T043 [US5] Tests in `tests/test_web_prep.py`: US5 scenario 1 (while running, the fragment polls and a second POST returns the same run); the result is announced once in the banner if the page was not open.

---

## Phase 8: Polish and cross-cutting

- [ ] T044 Create `tests/test_parity.py` (FR-001 / SC-003). For add, score, generate and prep, run the action via the CLI (`CliRunner`) and via the web (`TestClient` + `SyncRunner`) against two fresh workspaces with identical mocked clients. Compare stored rows (ids and timestamps excluded), file names and `.docx` text, and `runs.jsonl` records with `source`, `run_id` and `ts` excluded.
- [ ] T045 [P] Create `tests/test_workspace_isolation.py` (SC-007): run every service against two workspaces in one process and assert no rows, files, log records or `ui_runs` cross.
- [ ] T046 [P] Create `tests/test_layering.py`: AST-scan `jobagent/services/` for imports of `typer`, `rich`, `jobagent.cli` or `jobagent.config.get_config`, and for calls to `print`/`sys.exit`. Scan `jobagent/web/` for imports of `jobagent.core.store` write functions and `jobagent.adapters.llm.get_client` (web goes through services only).
- [ ] T047 [P] Update `README.md` with a `jobagent ui` section (start, stop, what costs money, supersede) and `generate --supersede`. Update `CLAUDE.md`: the `source` values now include `ui`, the test count, and `jobagent ui   free` in the command table.
- [ ] T048 Run the manual walkthrough in `specs/001-local-ui/quickstart.md` against a throwaway store. **This costs about $0.30 in model calls: ask Alan before running it.**
- [ ] T049 Before the final commit, scan `git diff main --stat` and the full diff of `specs/`, `tests/` and `jobagent/web/templates/` for real employer names, salary figures and never-publish facts (Constitution VI).

---

## Dependencies

```text
Setup (T001–T004)
  └─► Foundational (T005–T018)
        ├─► US1 (T019–T024) ─► US2 (T025–T030)      ← MVP
        ├─► US3 (T031–T037)      needs T019–T022 for the detail page it lands on
        ├─► US4 (T038–T040)      needs T019 (OutputFolders) and T022
        └─► US5 (T041–T043)      needs T022
Polish (T044–T049) after the stories it covers
```

Inside Foundational: T005 needs T010 (the `DocumentStore` type), so do T010 first or stub the type. T007 → T008 → T010. T011 → T016 → T017 → T018. T012 → T013.
US2 renders into the detail page, so US1 comes before it. Every story's service
extraction (T025, T032–T033, T038, T041) is independent of the others.

## Parallel opportunities

- Setup: T002, T003, T004.
- Foundational: T006, T009, T012 and T014 alongside the T007→T008→T010 and T011→T016 chains.
- Once US1 is done: the service extractions for US3 (T031–T034), US4 (T038) and US5 (T041) can proceed alongside US2, because each touches a different CLI module and service file.
- Polish: T045, T046, T047.

## Implementation strategy

1. **MVP = Setup + Foundational + US1 + US2.** That is the BUILD_PLAN exit
   criterion. Stop there and use it on real ads before going further.
2. US3 next: it removes the last reason to open a terminal in the daily loop.
3. US4 and US5 when the CLI versions start to feel like friction.
4. SC-001 (a week of the loop with no command typed) is checked from `runs.jsonl`:
   `source: "cli"` records for `jd add`, `score` and `generate` that week should
   be zero.

Total: 49 tasks.
