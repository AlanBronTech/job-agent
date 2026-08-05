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

## Document format (non-negotiable — matches existing resumes)

- Body text 11pt, Calibri
- Line spacing 1.15
- 6pt spacing after every paragraph and table row
- Name heading 16pt bold; section headings 12pt bold, dark blue (#1F3864)
- Margins 1.5cm all round
- Single page target for cover letters; two pages max for resumes

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
