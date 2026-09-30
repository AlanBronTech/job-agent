# Implementation Plan: Local UI (Phase 8)

**Branch**: `001-local-ui` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-local-ui/spec.md`

## Summary

A localhost web UI that runs the daily loop (read the shortlist and an
assessment, add an ad, score it, generate documents, record status, prep) with
no command typed. Server-rendered pages over the same code the CLI runs.

The main work is not the screens. Reading the CLI commands shows that the
workflow logic the spec calls "guards" lives in `jobagent/cli/`: the
preconditions for generate, the skip overrule record, the overwrite check, the
write sequence, saved-page unwrapping and its truncation refusal, the thin-ad
refusal in score, date validation in apply, and the folder discovery used by
`jd delete`. A web handler calling `core/` alone would skip all of them. So the
plan starts by moving that logic into a service layer the CLI and the UI both
call, with the CLI's tests as the parity net. Only then does it add the move-aside
behaviour, the background runner and the pages.

The services are built for a hosted version that is not built here (FR-021–023).
Each takes a `Workspace`: whose profile, which store, which run log, where
saved ads are and where documents go. Documents go through a `DocumentStore`
interface, with one implementation, the local folder. The CLI and UI build a
`Workspace` from `.env` exactly as today. A hosted version would build one per
signed-in person and supply a different `DocumentStore`. No workflow code
changes.

## Technical Context

**Language/Version**: Python 3.12, `uv`

**Primary Dependencies**: existing stack, plus `fastapi`, `uvicorn`, `jinja2`,
`python-multipart` (see research R2). HTMX is vendored as one static file, with
no CDN and no build step.

**Storage**: the existing SQLite store, plus one new table `ui_runs`, created and owned by
`services/runs.py`. `core/store.py` and its schema version are unchanged.
Output folder on disk unchanged, except for the superseded-folder naming (data-model §2).

**Testing**: `pytest`; FastAPI `TestClient` (on `httpx`, already present through
the SDKs); model calls mocked as now; background runner replaced by a
synchronous one in tests.

**Target Platform**: macOS, one user, a browser on the same machine.

**Project Type**: CLI with a local web front end over a shared service layer.

**Performance Goals**: list and detail pages under 1 s with 100 ads (SC-002).
One output-folder scan per page, not one per ad.

**Constraints**: bound to 127.0.0.1 only; no network access beyond the model
provider calls already made; no model call without a displayed cost and a
confirmation; the page closing never cancels a run.

**Scale/Scope**: about 60 ads today, growing by about 5 a week. Seven pages or
fragments, eight actions.

## Constitution Check

*Gate before Phase 0, re-checked after Phase 1.*

| Principle | Status | How |
|---|---|---|
| I. Assistive, never autonomous | Pass | Ads enter only as uploaded files or pasted text (FR-007). No page fetches a URL. Output is files in `OUTPUT_DIR`. `source_url` is shown as text, not a link the server follows. |
| II. `core/` callable from anywhere | Pass | Orchestration moves *out of `cli/`* into `services/`, and web handlers call only that. Exactly one `core/` change, justified as a `core/` defect rather than a UI need: `expected_cost` in `core/spend.py`. CLAUDE.md requires stating a command's cost before spending, and the CLI never did, so the CLI prints it too. The `ui_runs` registry is UI state and lives in `services/runs.py`, not `core/store.py` (analysis C1, 2026-09-30). |
| III. Enforce mechanically | Pass | Cost confirmation, one run per ad, move-aside-not-overwrite, 127.0.0.1-only, Host check and CSRF are enforced in code and each has a test. Validation is unchanged and shown in full. |
| IV. Tests never touch the network | Pass | Model clients mocked; `TestClient` is in-process; the browser opener and `open` are injected and faked. |
| V. Money stated before spent | Pass | Every spending action goes through a cost estimate built from `runs.jsonl` (research R5). Expected cost per action: parse ~$0.03, score ~$0.11, generate resume + cover ~$0.13, prep ~$0.11. These are the measured figures from CLAUDE.md, and the UI recomputes them live rather than quoting them. The UI adds no new model call. |
| FR-021–023 (hosted readiness) | Pass | `Workspace` passed into every service; `DocumentStore` protocol; `ui_runs.workspace` column. A two-workspace test (SC-007) proves no state crosses. |
| VI. Repository is public | Pass | All examples in these specs are invented. Templates render data from the store at runtime; no fixture uses real content. The new test fixtures use the invented companies from spec.md. |

## Project Structure

### Documentation (this feature)

```text
specs/001-local-ui/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── services.md      # the service layer the CLI and UI share
│   ├── http.md          # routes, methods, guards
│   └── cli.md           # `jobagent ui`, `generate --supersede`
└── tasks.md             # /speckit-tasks
```

### Source Code

```text
jobagent/
  core/
        spend.py            # + expected_cost(): measured mean per action (a core/ fix: the CLI never stated cost)

  services/             # NEW — workflow orchestration shared by cli/ and web/
    __init__.py         # typed Refusal / result types
    workspace.py        # Workspace: profile dir, db, runs log, jd dir, DocumentStore, owner id
    ads.py              # add ad: resolve file, unwrap, truncation/thin checks, parse, store, attribute
    scoring.py          # score: thin-ad refusal, profile, client, store assessment
    documents.py        # generate: preconditions, overrule record, clash check, supersede, write
    prep.py             # prep
    pipeline.py         # apply / outcome with date validation; board grouping
        outputs.py          # documents on disk per ad, current + superseded
    runs.py             # ui_runs registry: owns its table, plain SQL
  adapters/
    docs.py             # + supersede_folder(), folders_for() (moved from cli/jd.py)
    document_store.py   # NEW — DocumentStore protocol + LocalFolderStore (wraps docs.py)
    desktop.py          # NEW — open file / reveal in Finder; used by LocalFolderStore only
  cli/
    generate.py, jd.py, score.py, prep.py, apply.py   # shrink to parse args → service → render
    ui.py               # NEW — `jobagent ui`
  web/                  # NEW — no business logic
    app.py              # FastAPI app factory, Host/CSRF middleware
    runner.py           # background runs: thread pool + ui_runs registry
    routes.py
    templates/*.html
    static/htmx.min.js, app.css
tests/
  test_services_*.py    # workflow behaviour, moved/duplicated from test_cli_*
  test_parity.py        # same action via CLI and via web → same rows, files, log records
  test_web_*.py         # routes, guards, runner, announcements
```

**Structure Decision**: a new `jobagent/services/` package between `cli/`/`web/`
and `core/`+`adapters/`. It carries the rules of `core/`: no print, no typer, no
`sys.exit`. Outcomes come back as result objects, and refusals as typed exceptions
carrying the facts a renderer needs. The CLI keeps its wording, and the UI words
the same facts its own way.

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|
| New `services/` layer not in CLAUDE.md's architecture | The orchestration FR-002 requires both front ends to share writes files through `adapters/docs.py` and `docx_writer`. `core/` is specified as "no I/O side effects beyond the store". | **Into `core/`**: breaks that rule for the first time and blurs the line that keeps `core/` testable without a filesystem. **Leave it in `cli/` and call CLI functions from the web**: they print and raise `typer.Exit`, so the web would parse exit codes. **Duplicate it in `web/`**: two copies of every guard. That is the thing FR-002 exists to prevent. |
| New table `ui_runs`, owned by `services/runs.py`, not `core/store.py` | FR-016a/b: a run outlives its page, is announced once, and is known to be interrupted after a restart. | **In-memory registry**: loses FR-016b across a restart, and cannot tell "interrupted" from "never happened". That is the same shape as the failed-call logging bug. **A JSON file**: a second persistence mechanism beside SQLite for no gain. |
| `Workspace` and `DocumentStore` abstractions with one implementation each | FR-021–023. A hosted version is the stated direction (2026-09-29). Threading config through later means touching every service and every test again. | **Wait until hosting is real**: the services are being written now, and passing a context in now costs a parameter; retrofitting it costs a second pass over the same code. **A full multi-tenant model now**: builds sign-in and per-user storage nobody uses yet. |
| Four new dependencies | See research R2. | **stdlib `http.server`**: hand-rolled routing, form and multipart parsing, and templating. That is more code for Alan to read than the dependencies cost. |

**Decided 2026-09-29 (Alan)**: `services/` as a separate layer. CLAUDE.md's
Architecture section is updated to add it as part of this feature.

## Post-design Constitution Re-check

Re-checked after writing data-model.md and the contracts. No change: the `ui_runs`
table stores results the UI already showed and adds no fact that is not in the store or
on disk. `desktop.py` refuses any path outside `OUTPUT_DIR`. The HTTP contract has
no route that takes a URL, and none that writes outside `JD_DIR` and `OUTPUT_DIR`.
