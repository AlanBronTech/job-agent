# CLAUDE.md — job-agent

## What this is

A personal, interactive job-application agent for Alan Bron. It ingests job
descriptions, scores them honestly against a structured profile, generates
tailored resumes and cover letters as .docx into a local folder, and tracks the
application pipeline.

It is **assistive, not autonomous**. It never submits an application. The human
reviews every generated artefact before it goes anywhere.

## Hard rules — do not violate these

1. **No scraping of Seek or LinkedIn.** Both prohibit automated access in their
   terms of use. Do not fetch, parse, or navigate seek.com.au or linkedin.com
   job pages, logged-in or otherwise. Do not add Selenium, Playwright, or any
   headless browser. If a task seems to require it, stop and say so.
   - Permitted: accepting JD text Alan pastes, or a page he has already
     opened and saved himself as PDF, .mhtml or .txt.
   - Permitted: reading the SEEK and LinkedIn alert *emails* sent to Alan
     (`jobagent alerts`, IMAP, read-only). The email only — never the job
     page it links to.
2. **No invented experience.** All resume and cover-letter content must be
   selected and reweighted from `profile/`. If the profile lacks material for a
   requirement, the output must say so as a gap, not fabricate. Prompts must
   state this explicitly and generated output must be validated against the
   profile where feasible.
3. **No auto-submission.** The agent produces artefacts and instructions. It
   does not fill in or submit web forms.
4. **Voice.** Generated prose follows `profile/voice.md`: blunt, factual,
   engineering register. No sycophancy, no "I am thrilled to apply", no
   "passionate about". If a draft contains banned phrases, regenerate.

## Architecture

Thin CLI over a service layer, so a FastAPI/HTMX UI can be added later without
touching business logic.

```
jobagent/
  core/          # pure logic, no I/O side effects beyond the store
    profile.py   # load + validate profile/*.yaml
    jd.py        # JD parsing to structured JobDescription
    scoring.py   # fit scoring, gap analysis, go/no-go
    generate.py  # resume + cover letter + application answers
    prep.py      # interview prep from JD + story bank
    alerts.py    # alert emails → listings, and the title/pay filter
    store.py     # SQLite pipeline persistence
    models.py    # pydantic models shared everywhere
  adapters/      # everything that talks to the outside world
    llm.py       # Anthropic API client, JSON-mode helpers, retries
    docs.py      # writing generated documents to the local output folder
    docx_writer.py  # python-docx rendering to Alan's format
    document_store.py  # where documents live; LocalFolderStore is the only one
    mailbox.py   # alert emails over IMAP (read-only) or from .eml files
  services/      # workflows shared by cli/ and web/ (added 2026-09-29)
    workspace.py # whose profile, store, run log, saved ads, document store
  cli/           # typer commands — parse args, call services, render
  web/           # local UI: routes + templates over services/, no logic
```

Rule: `core/` must be callable from a web handler with no changes. No `print`,
no `typer` imports, no `sys.exit` inside `core/`.

Rule: `services/` holds the orchestration shared by `cli/` and `web/` —
preconditions, refusals, write order — so both enforce the same guards. It
may do I/O through `adapters/`, but has no `print`, no `typer`, no
`sys.exit`, and never calls `get_config()`: every function takes a
`Workspace`. Refusals are typed exceptions carrying facts; `cli/` and
`web/` word them (specs/001-local-ui, 2026-09-29).

## Stack

- Python 3.12, `uv` for env and deps
- `typer` (CLI), `pydantic` v2 (models), `rich` (output)
- `anthropic` (LLM), `python-docx` (documents), `PyYAML` (profile)
- `pypdf` (reading job ads saved as PDF; counting rendered resume pages)
- LibreOffice, optional and outside the dependency list: `soffice --headless`
  renders a resume so its pages can be counted
- `sqlite3` from stdlib — plain SQL, no ORM
- `fastapi`, `uvicorn`, `jinja2`, `python-multipart` (the local UI); HTMX
  vendored as one static file, no build step, nothing loaded from a CDN
- `pytest` for tests; `httpx2` so Starlette's TestClient does not warn

Keep the dependency list short. Alan's Python is his weakest recent language;
readable stdlib beats clever abstractions.

## Document format (non-negotiable)

Source of truth: `~/Documents/AlanBronResumeMaster102026.docx`, revised Oct 2026.
Every value below was measured from the master, not chosen. If a spec and the
master disagree, the master wins and this section gets corrected (D48).

### Typography

- Body text **10.5pt Calibri**; line spacing **1.1** throughout
- Name **26pt bold**, `#1B3A6B`; tagline 10.5pt `#2258A5`; contact line
  9.5pt `#595959`
- Section headings **11.5pt bold `#1B3A6B`**, all caps, 11.5pt before /
  5.5pt after
- Role headings 11.5pt bold, near-black, 9pt before / 1pt after
- Bullets 10.5pt, 1.5pt before / 3.6pt after
- Margins **1.68cm left/right, 1.32cm top, 1.23cm bottom** on A4
- Spacing is deliberately tight and varies by element. There is no global
  "6pt after every paragraph" rule.

### Resume structure

Section order, exactly:

1. **Name / tagline / contact** — contact on one line, `·` separated
2. **PROFILE** — two short paragraphs, no heading bullet
3. **CAREER HIGHLIGHTS** — 5 bullets, each opening with a bold label then
   an em dash (`AI in production — ...`)
4. **CORE SKILLS** — borderless 4×2 table, 8 labelled categories, label in
   caps above a comma-separated list
5. **EXPERIENCE** — reverse chronological, 1–4 bullets per role
6. **EARLIER CAREER** — one condensed bullet each, undated
7. **EDUCATION & CERTIFICATIONS** — one line each, certifications first

Role heading format is `Title  ·  Company` with the date range right-aligned
on a tab stop at **16.93cm**.

### Dates

- Roles render as **years only** (`2025 – 2026`, `2026 – Present`);
  `roles.yaml` stores `YYYY-MM` and the renderer truncates.
- Founder entries in EARLIER CAREER **show years**, pre-2017 included, in the
  master's style (`2006–16`). Dates up to ~20 years back may be shown;
  **computed career length is never shown** (Alan, 2026-10-04; re-confirmed
  2026-10-16). `earlier_career` entries stay undated.
- **An ongoing venture is evidence, not record** (D1): DataLlama appears as a
  CAREER HIGHLIGHT and one part-time line under Bron Consulting, never in
  EARLIER CAREER, never as full-time work or a gap-filler.

### Length

- Cover letters: one page, body under 350 words (contract notes 220).
  Measure the body, not the rendered page (D24).
- Resumes: about 2.5 pages, never more than 3; a contractor CV (contract ad
  matched to an offer) 1.5-1.75 pages (Alan, 2026-10-23). Measured by
  rendering through LibreOffice (`adapters/pages.py`); over the limit is a
  blocker after one reselection.

## LLM usage

- All model calls go through `adapters/llm.py`; the model string comes from
  config, never a call site. Prompts live in `prompts/*.md`, versioned.
- JSON-only output, parsed defensively, one retry with the error fed back.
  Drop keys the model volunteers rather than fail the call.
- Stream long outputs (D2). Transport failures are classified in
  `_complete_with_retry`, not only per client (D3). 401 is not retried.
- Every call, failed ones included, is logged to `runs.jsonl` with `command`,
  `jd_id`, `source`, `run_id` (D4, D21). A missing `outcome` means success.
- Reasoning effort is set per call type (`DEFAULT_EFFORT`, D5); output
  ceilings are sized for the reasoning (D6).
- Cheap steps get cheap models by default (`CHEAP_DEFAULTS`, D7); a route in
  `.env` or on the Settings page wins. Settings live in `settings.json`
  beside the database and are applied on every request (D8).

## Where the project is — 2026-10-23

Built and merged on `main`: phases 0-5 and 7; specs 001 (local UI), 002
(reapplication, batch), 003 (generation quality); the demo, Settings, cheap
defaults, the first-pass screen; REVIEW-2026-10-16 fixes; REVIEW-2026-10-18
tasks 1 (sent copies, `diff`), 2 (`revise`, `context`), 3 (story mechanism
fields), 5 (contacts), 7 (contract framing, day-rate filter, cover note,
contractor CV), 9
(`checklists/final-review.md`), 11 (this file; history in
`docs/decisions.md`); the claim check on the resume's PROFILE and highlights;
`jobagent alerts` (SEEK/LinkedIn alert emails → a filtered list of links,
and Alan's decision on each, schema v17; UI page Alerts).
Phase 6 (Gmail triage) and the Drive upload were dropped (`BUILD_PLAN.md`).

Not built: the edits classification table and `edits report` (task 1 — wait
until enough edited pairs exist to read by hand first), task 8 (needs that
data), 001's pipeline board and prep in
the UI, run-log rotation. Task 4 was cut to the write-up only; task 6 waits;
REVIEW-2026-10-16 D7 is rejected.

**Standing decisions not to re-open:** founder years stay on the resume; the
review is off by default, the claim check on; the UI says "Jobs", not "Ads";
`job_agent` stays "directed with Claude Code", no line/commit-count bullets.

`main` is pushed to a **public** GitHub repo. `.env`, `profile/`, the
database, `runs.jsonl`, `evals/cases.yaml` and `REVIEW-*.md` are gitignored
and must stay that way; the history was purged once (D49). Anything committed
uses invented examples.

Costs: never quote one from memory or a file when `jobagent spend` can answer
it. Every paid command and the UI's confirmation page print the expected cost
before spending (`services/costs.py`). `README.md` documents the loop for
Alan; keep it accurate — he uses it.

## Design invariants

Each is one line here; the story of how it was learned is in
`docs/decisions.md` under its number. Read the entry before changing the code
it protects.

- Hard filters are computed in Python; judgment is asked of the model. A
  breach overrides the verdict. "Not stated" is not "fine" (D9).
- For the resume the model returns references, not prose; bullet text is
  copied verbatim from `profile/` (D10).
- A highlight may cite more (entry ids, `earlier_career`) than a bullet may
  copy (D11).
- `core/validation.py` enforces the hard rules mechanically (D12).
- In `profile/`, `text` is rendered and `note_for_scorer` is not (D13).
- The writer never sees `note_for_scorer`; writing rules go in
  `note_for_writer`, which holds rules only, never facts (D14).
- The number haystack is built by exclusion: `voice`, `note_for_scorer`,
  `phone`, `*_rationale`, `visibility: scorer_only` (D15). It is unit-blind;
  never describe it as stronger than that (D16).
- The eval grades "was this worth applying to", never "was he hired" (D17).
- Company history is reported, never scored (D18).
- Documents on disk are state: check `OUTPUT_DIR`, not only SQLite (D19).
- Prices live in `prices.yaml` with `checked_on`; an unpriced model is
  `price_unknown`, never $0 (D20). Estimates price past tokens at today's
  rates (D30).
- Before inferring from a status field, ask what the enum cannot say (D22).
- `generate` lists unused entries on every run; a list, not a warning (D23).
- Strip both ends of a letter, and only a bare closing (D24).
- Check what a constraint displaced, and that the writing model was shown it
  at all (D25).
- `jd delete` refuses with an application row and never touches
  `OUTPUT_DIR` (D26). Amend the record holding the application; never move
  the application (D27). `jd amend` keeps `superseded_text` (D28).
- Audit the public repo's history, at blob level, before claiming it (D29).
- A guard that moves things runs after every refusal, before any spend (D31).
- The six-month rule is a refusal before spending, not a hard filter (D32).
- Excluded evidence is removed from the writer's input and re-checked on
  output (D33).
- A paid check never loses the documents (D34). A surviving blocker puts
  `_NOT-READY` in the file name (D35). Reuse caps bind because failing
  forces a rewrite (D36).
- Admit a gap only in a firm must-have (D37). Claims about order are
  blockers (D38).
- The first-pass screen is advice and stays cautious: 0 worthwhile jobs
  skipped is the number to keep (D39).
- A guard that fires when nothing is at risk stops being a guard (D40).
- A variable informs nothing unless it was observable at decision time (D41).
- Alerts are filtered by code, not a model: a title alone is too little to
  judge. Suggest, maybe or skip, each with its reason, so `--skipped` can
  audit the filter; Alan's decision is recorded apart from the verdict.
- Read the prompt before blaming the model (D42); a weaker model finds
  underspecified prompts (D43); a cross-model comparison is not a prompt
  regression (D44); one run of a boundary case is a coin flip (D45).

## Testing

- `core/` gets real unit tests with fixture JDs in `tests/fixtures/`. LLM
  calls are mocked; the test suite strips provider API keys so a forgotten
  fake fails instead of billing. `evals/` hits the real API, never in CI.
- The eval set is built from the `applications` table and graded against
  Alan's retrospective judgment. It is a **regression detector, not a
  measurement**: report "no regression", never a percentage (D46). Watch
  the separation, not the accuracy; do not tune on agreed skips; same-prompt
  noise is ~6 points, so re-run a flipped case before believing it (D47).

## Working style

- Small commits, one phase at a time. Do not build ahead of the plan.
- Run the tests after each change.
- When a design decision has a real trade-off, state it and ask rather than
  picking silently.
- Alan is a 35-year engineer. Explain reasoning, skip tutorials.
- Model calls cost real money and some take minutes. Say what a command will
  cost before spending it, and prefer the free path (`eval report`, `score
  --last`) when it answers the question.
- Any value in profile YAML that begins with a quote or special character
  must use a >- folded block. The loader surfaces YAML parse errors with the
  offending line, not a raw traceback.
