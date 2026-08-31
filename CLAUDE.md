# CLAUDE.md — job-agent

## What this is

A personal, interactive job-application agent for Alan Bron. It ingests job
descriptions, scores them honestly against a structured profile, generates
tailored resumes and cover letters as .docx into Google Drive, and tracks the
application pipeline.

It is **assistive, not autonomous**. It never submits an application. The human
reviews every generated artefact before it goes anywhere.

## Hard rules — do not violate these

1. **No scraping of Seek or LinkedIn.** Both prohibit automated access in their
   terms of use. Do not fetch, parse, or navigate seek.com.au or linkedin.com
   job pages, logged-in or otherwise. Do not add Selenium, Playwright, or any
   headless browser. If a task seems to require it, stop and say so.
   - Permitted: reading Alan's own Gmail inbox for job-alert emails he
     subscribed to; accepting JD text he pastes or saves to a file.
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
    store.py     # SQLite pipeline persistence
    models.py    # pydantic models shared everywhere
  adapters/      # everything that talks to the outside world
    llm.py       # Anthropic API client, JSON-mode helpers, retries
    gmail.py     # OAuth, alert-email fetch + parse
    drive.py     # docx upload to known folders
    docx_writer.py  # python-docx rendering to Alan's format
  cli/           # typer commands — thin, no logic
```

Rule: `core/` must be callable from a web handler with no changes. No `print`,
no `typer` imports, no `sys.exit` inside `core/`.

## Stack

- Python 3.12, `uv` for env and deps
- `typer` (CLI), `pydantic` v2 (models), `rich` (output)
- `anthropic` (LLM), `python-docx` (documents), `PyYAML` (profile)
- `google-api-python-client` + `google-auth-oauthlib` (Gmail, Drive)
- `sqlite3` from stdlib — plain SQL, no ORM
- `pytest` for tests

Keep the dependency list short. Alan's Python is his weakest recent language;
readable stdlib beats clever abstractions.

## Document format (non-negotiable)

Source of truth: `~/Documents/AlanBronResumeMaster2026.docx`, written Aug 2026.
Every value below was measured from that file, not chosen. The earlier version
of this section was wrong on all six values — if a future spec and the master
disagree, the master wins, and this section gets corrected.

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

- Roles render as **years only** (`2025 – 2026`), current role as
  `2026 – Present`. `roles.yaml` stores `YYYY-MM`; the renderer truncates.
- Founder entries in EARLIER CAREER **do** show years, including pre-2017
  (`2006–16`). See the age-signal policy in `profile/roles.yaml` — dates are
  shown, career length is never computed.
- `earlier_career` entries stay undated.

### Length

- Cover letters: one page, under 350 words (see `profile/voice.md`)
- Resumes: two pages max

## LLM usage

- All model calls go through `adapters/llm.py`. Model string comes from config,
  never hardcoded at call sites.
- Prompts live in `prompts/*.md` as versioned files, loaded at runtime. Never
  inline a long prompt in Python.
- Structured output: instruct JSON-only, parse defensively, retry once on
  parse failure with the error fed back.
- Log every call (prompt name, tokens, cost estimate) to `runs.jsonl` for the
  eval harness.

## Testing

- `core/` gets real unit tests with fixture JDs in `tests/fixtures/`.
- LLM calls are mocked in unit tests. There is a separate `evals/` path that
  hits the real API and is never run in CI.
- The eval set is ~15 real JDs Alan applied to, with known outcomes. The fit
  scorer is measured against those outcomes. This is the part that makes the
  project credible in an interview — treat it as a first-class deliverable, not
  an afterthought.

## Working style

- Small commits, one phase at a time. Do not build ahead of the plan.
- Run the tests after each change.
- When a design decision has a real trade-off, state it and ask rather than
  picking silently.
- Alan is a 35-year engineer. Explain reasoning, skip tutorials.
- Any value in profile YAML that begins with a quote or special character must use a >- folded block. The loader should surface YAML parse errors with the offending line, not a raw traceback.
