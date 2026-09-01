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
    docs.py      # writing generated documents to the local output folder
    docx_writer.py  # python-docx rendering to Alan's format
  cli/           # typer commands — thin, no logic
```

Rule: `core/` must be callable from a web handler with no changes. No `print`,
no `typer` imports, no `sys.exit` inside `core/`.

## Stack

- Python 3.12, `uv` for env and deps
- `typer` (CLI), `pydantic` v2 (models), `rich` (output)
- `anthropic` (LLM), `python-docx` (documents), `PyYAML` (profile)
- `pypdf` (reading job ads saved as PDF)
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

## Where the project is — 2026-09-01

**Built and working. Phases 0-5 and 7 are done; only Phase 8 (a local UI) is
left, and it is deferred until the CLI has been used on real applications.**
Phase 6 (Gmail triage) and the Drive upload were dropped — see `BUILD_PLAN.md`
for the reasoning, which matters more than the decisions.

312 tests pass, none touching the network. `main` is pushed to a **public**
GitHub repo; `.env`, `profile/`, the database, `runs.jsonl` and
`evals/cases.yaml` are gitignored and must stay that way.

The commands, and roughly what each costs:

    jobagent jd add --file <ad>        ~$0.08   parse an ad, print a JD id
    jobagent score <id>                ~$0.20   verdict, two scores, filters
    jobagent generate <id> --resume --cover  ~$0.30  documents + assessment
    jobagent prep <id>                 ~$0.15   interview questions
    jobagent apply|outcome|status      free     the pipeline
    jobagent eval report|diff|export   free     grade the scorer
    jobagent eval run                  ~$0.19/case
    jobagent --budget <cmd>            free tier, 20 requests/day, worse

`README.md` documents the loop for Alan. Keep it accurate — he uses it.

## Design invariants — these were expensive to learn

- **Hard filters are computed in Python; judgment is asked of the model.**
  Salary floor, employment type, on-site geography, closed ads — arithmetic
  and set membership over decisions Alan has already made. A breach overrides
  the model's verdict outright. `ConstraintStatus` has three values because
  "the ad does not say" is not "the ad is fine".
- **For the resume the model returns references, not prose.** It picks roles,
  bullets and ordering by id; the text is copied verbatim from `profile/`. A
  model that cannot type a bullet cannot embellish one. It writes prose only
  for the tagline, the PROFILE paragraphs and the cover letter — all validated.
- **`core/validation.py` enforces the hard rules mechanically**, not by asking
  a prompt nicely: every number traced to the profile, the banned list parsed
  out of `voice.md` at runtime, explicit patterns for the age-signal policy.
- **In `profile/`, `text` is rendered and `note_for_scorer` is not.** A
  cross-reference left in a bullet's `text` was copied onto a real resume.
- **The eval harness grades "was this worth applying to", never "was he
  hired".** Alan was offered the Easy Signs job and applying was still the
  wrong call — the commute that ended it is an absolute filter in his profile.
  Grading on hiring outcomes would tune away the constraint that mattered.
- **Check a variable was observable at decision time before it informs
  anything.** Applicant counts read off a page saved weeks later are target
  leakage; they were not there when he decided.
- **Read the prompt before blaming the model.** Two sessions were spent
  attributing over-split requirements to Gemini, then to Claude. The v1 prompt
  instructed it.
- **A weaker model is a prompt-underspecification detector.** Running the eval
  set through free-tier Gemini found that the v2 scoring prompt never stated
  the 0-100 range. Claude had been filling it in from convention.

## Testing

- `core/` gets real unit tests with fixture JDs in `tests/fixtures/`.
- LLM calls are mocked in unit tests. There is a separate `evals/` path that
  hits the real API and is never run in CI.
- The eval set is 14 real applications with known outcomes, built from the
  `applications` table rather than a hand-written file, so it cannot go stale
  through neglect. The fit scorer is measured against Alan's retrospective
  judgment of each. This is the part that makes the project credible in an
  interview — treat it as a first-class deliverable, not an afterthought.
- Current standing: the scorer agrees on 10 of 14, and **all four of its errors
  are false negatives** — it says skip on roles Alan judges he fits. It weights
  role shape and ad structure; he weights requirement match. **Do not tune this
  on fourteen cases.** `generate --force` records each time he overrules it, and
  `eval report` reports who was right; the threshold moves on that evidence.

## Working style

- Small commits, one phase at a time. Do not build ahead of the plan.
- Run the tests after each change.
- When a design decision has a real trade-off, state it and ask rather than
  picking silently.
- Alan is a 35-year engineer. Explain reasoning, skip tutorials.
- Model calls cost real money and some take minutes. Say what a command will
  cost before spending it, and prefer the free path (`eval report`, `score
  --last`) when it answers the question.
- Any value in profile YAML that begins with a quote or special character must use a >- folded block. The loader should surface YAML parse errors with the offending line, not a raw traceback.
