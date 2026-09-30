# Research: Local UI (Phase 8)

Phase 0. Each entry: decision, rationale, alternatives. No NEEDS CLARIFICATION
remains in the Technical Context.

## R1. Where the shared workflow logic lives

**Decision**: new `jobagent/services/` package; `cli/` and `web/` both call it.

**Rationale**: reading `cli/generate.py`, `cli/jd.py`, `cli/score.py`,
`cli/prep.py` and `cli/apply.py` shows these rules living in the command layer:

| Rule | Today |
|---|---|
| generate needs a scored ad; refuses a skip without an overrule, and records the overrule | `cli/generate.py:generate`, `_record_override` |
| refuse before spending if this run would replace files | `cli/generate.py:_refuse_to_clobber`, `_planned_documents` |
| write order: resume, letter, answers, then `assessment.md` + `job-ad.md` | `cli/generate.py:generate` |
| saved page unwrapping; refuse a truncated capture; warn on a thin one | `cli/jd.py:add`, `_extract_saved_page` |
| attribute the parse call once the JD id exists | `cli/jd.py:add` |
| refuse to score a thin ad without `--force` | `cli/score.py:score` |
| no future dates; a repost cannot postdate the application | `cli/apply.py:_parse_date`, `apply` |
| find every output folder for an ad, any month | `cli/jd.py:_folders_for` |

Each becomes a service function returning a result or raising a typed refusal,
for example `AlreadyGenerated(folder, files)`, `VerdictIsSkip(rationale)` or
`CaptureTruncated()`. The CLI maps a refusal to its existing message and exit
code, so the CLI tests pass unchanged. That is the parity net for the move.

**Alternatives**: into `core/` (breaks "no I/O beyond the store"); call CLI
functions from web handlers (they print and `typer.Exit`); duplicate in `web/`
(what FR-002 forbids). **Decided by Alan, 2026-09-29.**

## R2. Web stack

**Decision**: FastAPI + uvicorn + Jinja2 + python-multipart. HTMX 2.x is vendored
into `web/static/`, committed and served locally.

**Rationale**: BUILD_PLAN names FastAPI/HTMX. FastAPI's pydantic v2 is already a
dependency, and `TestClient` runs on `httpx`, which the SDKs already pull in.
Pages are server-rendered. HTMX is used for two things only: polling a running
action's status fragment, and swapping the confirmation panel in place. There is
no build step, and nothing loads from the network, so the UI works offline
except for the model calls themselves. `python-multipart` is needed only for the
file drop.

**Alternatives**: stdlib `http.server` (routing, multipart and templating by hand:
more code than the dependencies); Starlette without FastAPI (saves one package and
loses form/validation helpers Alan would otherwise write); plain meta-refresh
polling with no JS (workable, but it reloads the whole page every few seconds and
loses scroll position on a long assessment). The dependencies go in the main
dependency list, not an extra: four packages, and `uv sync` keeps working.

## R3. Background runs (FR-006, FR-016a/b)

**Decision**: an in-process `ThreadPoolExecutor(max_workers=2)` owned by the web
app, with every run recorded in a new `ui_runs` table (data-model §1).

- Starting a run inserts a row `running`. The insert is refused if a row for the same
  ad is already `running`. That check-and-insert happens in one SQLite
  transaction (`BEGIN IMMEDIATE`), so a double click cannot start two runs.
- The worker calls the service function, then writes `succeeded` or `failed`
  with a JSON result summary.
- Pages poll the run's fragment while it is `running`. The page closing affects
  nothing server-side.
- Every page renders a banner of finished runs with `seen_at IS NULL`. Opening the
  ad's detail page, or dismissing the banner, sets `seen_at`.
- On server start, any row still `running` becomes `interrupted`. Its model
  calls may or may not be in `runs.jsonl`: a killed process logs nothing, as a
  killed CLI command logs nothing. The banner says that rather than guessing.

**Alternatives**: a task queue (Celery, RQ: a broker for one user);
`asyncio` tasks (the LLM adapter is synchronous and streams on a blocking socket,
so it would need a thread pool anyway); one worker (a two-minute prep would block
scoring a different ad for no reason).

## R4. Superseding an existing folder (FR-017, FR-017a)

**Decision**: rename the current month's folder in place, from
`2026-09_AcmeLogistics_EngineeringManager` to
`2026-09.superseded-20260929T140512_AcmeLogistics_EngineeringManager`.
Implemented in `adapters/docs.py:supersede_folder()` with `os.rename`, and
refused if the target exists.

**Rationale**: `_folders_for` finds an ad's folders by the text after the first
`_`. A prefix with no underscore in it keeps that suffix intact, so every
existing "has this been done" lookup finds superseded folders with no change,
and they stay beside the current one in Finder. `os.rename` within one directory
is atomic on APFS: the folder is either fully moved or untouched, which is what
the spec's "if the move fails, nothing is spent" needs. The move runs *before*
the client is built, so a failure costs nothing.

**Alternatives**: a `_superseded/` subdirectory (moves it out of sight and out of
`_folders_for`'s glob, so FR-017a would need a second lookup); renaming files
rather than the folder (a half-renamed folder is a worse state than either
end); a zip (not reviewable in Finder).

## R5. Expected cost (FR-004, FR-005)

**Decision**: a new pure function, `core/spend.py:expected_cost(records, labels,
model)`. It takes successful records for each prompt label on the model the route
currently resolves to, sums them per `run_id` (so a retried parse counts as one
action costing two calls), and averages across run_ids. The result per label is
`(mean_usd, samples)` or `None`. Generate adds together the labels selected:
`generate_resume`, `generate_cover_letter`, `generate_answers`.

**Rationale**: FR-005 says measured, not constant. Averaging per call would
under-state an action that retries. Filtering by the routed model stops a
budget-mode or Gemini history pricing a Sonnet run. When there is no sample:
"no measurement for <model> yet" is shown, and confirmation is still allowed
(spec edge case). In budget mode: "free tier" is shown.

**Alternatives**: the constants in CLAUDE.md (they go stale; that is the price-table lesson);
`by_command` from `build_report` (mean per call, not per action, and mixes models).

## R6. Local-only access and CSRF (FR-018)

**Decision**, three layers, each tested:

1. Bind `127.0.0.1` only. `--host` is not exposed.
2. Reject any request whose `Host` header is not `127.0.0.1:<port>` or
   `localhost:<port>`. This defeats DNS rebinding, where a web page in another tab
   resolves its own name to 127.0.0.1 and talks to the UI.
3. Every POST needs a per-start random token. `jobagent ui` opens
   `http://127.0.0.1:<port>/?t=<token>`, the server sets it as an `HttpOnly`,
   `SameSite=Strict` cookie, and forms echo it in a hidden field. A POST whose
   field and cookie do not match is refused. Any other site in the same browser can
   send a POST to localhost, and without this a page could spend money on a
   `score` of its choosing.

**Alternatives**: bind only and trust it (FR-018 covers reachability, but not other
pages in the same browser); a password (friction for one user on one machine).

## R7. Opening documents (FR-016c)

**Decision**: `adapters/desktop.py` with `open_file(path)` → `open <path>` and
`reveal(path)` → `open -R <path>`, via `subprocess.run` with an argument list.
Both refuse any path that does not resolve inside `OUTPUT_DIR`. The web route
takes an ad id and a filename, never a path.

**Rationale**: the server and the person are on the same machine (FR-018), so
the server opening Word *is* opening it for Alan. Confining it to `OUTPUT_DIR`
means a forged request can at worst open one of his own documents.

## R8. Ad intake from the browser (FR-012)

**Decision**: a dropped file is written into `JD_DIR` under its own name (refused
if a different file of that name exists; reused if identical), then goes through
the same `services.ads.add(file=...)` path as `jd add --file`. "Newest saved ad"
calls `latest_ad`. Pasted text goes through the `--stdin` path. Accepted
types are exactly `AD_SUFFIXES` (`.pdf`, `.mhtml`, `.txt`), the set `jd add` accepts.

**Rationale**: keeping the file in `JD_DIR` preserves the CLI's assumption that
the saved ad lives there, and later `--file <fragment>` works on it. The name to
be parsed is shown before the cost confirmation.

## R9. Run-log `source` for UI calls

**Decision**: `RunContext(source="ui")`. `spend` already groups by whatever
string is there, and treats anything other than `eval` as real work.

**Rationale**: SC-001, a week of the loop with no command typed, is then
measurable from `runs.jsonl`: count `source: "cli"` records for `jd add`,
`score` and `generate` that week. This is the one deliberate difference from
FR-001's "same run-log entries". The parity test compares records with
`source`, `run_id` and `ts` excluded. CLAUDE.md's description of `source`
(`cli` or `eval`) gets `ui` added.

## R10. Server lifetime

**Decision**: `jobagent ui` runs uvicorn in the foreground and opens the browser
once it is listening. Ctrl-C stops it, and while a run is active it first asks
for a second Ctrl-C. Port 8765 by default, `--port` to change it. If the port is
busy, it exits naming the URL, because another instance is the likely cause.

**Rationale**: a daemon means launchd, a PID file and a stop command, all to save
one terminal tab. Foreground makes "the server stopped mid-run" something Alan
did knowingly, and R3's `interrupted` state covers it.

## R11. Workspace context (FR-021, FR-023)

**Decision**: a frozen dataclass `services.workspace.Workspace` with `owner`
(`"local"` for now), `profile_dir`, `db_path`, `runs_log_path`, `jd_dir` and
`documents: DocumentStore`. Every service function takes it as its first
argument. `Workspace.from_config(config)` builds today's one from `.env`, and
the CLI and web app call it once per command or request. Model routing and API
keys stay process-wide: the operator pays for model calls, in a hosted version too.

**Rationale**: `get_config()` is an `lru_cache`d global read from inside
commands today. A service that reads it cannot serve two people in one
process. Passing the context in is the whole change, and SC-007's two-workspace
test proves it. The `owner` column on `ui_runs` is the only per-person
record this feature adds.

**Alternatives**: a context variable (implicit, and exactly the global state
this removes); per-user processes (defers the problem and multiplies cost).

## R12. Document storage interface (FR-022)

**Decision**: `adapters/document_store.py` defines a `DocumentStore` protocol:
`folder_state(jd, when)`, `write(jd, when, name, bytes|text)`, `supersede(jd, when)`,
`list_for(jd)` and `open(ref)` / `reveal(ref)`. Its one implementation,
`LocalFolderStore`, wraps the existing `docs.py` functions and `desktop.py`.
Services refer to documents by `(jd, folder, name)`, never by a filesystem
path. Paths exist inside `LocalFolderStore` only.

**Rationale**: the move-aside rule, "has this been done" and opening a
document are the three places the local folder leaks into workflow logic. A
hosted store would implement the same five operations over object storage and
make `open` a download. `docx_writer` keeps writing to a path: `LocalFolderStore`
hands it one, and a hosted store would hand it a temp file. That is recorded
here so nobody changes the writer for it.

**Alternatives**: abstract the filesystem generically (a VFS layer: far more
surface than five operations need).
