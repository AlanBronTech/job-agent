# job-agent Constitution

This file is deliberately short. `CLAUDE.md` holds the hard rules and the design
invariants with the incidents that produced them, and it is the source of truth.
This constitution names what every spec, plan and task must satisfy, and points
there for the reasoning. Where the two disagree, `CLAUDE.md` wins and this file
gets corrected.

## Core Principles

### I. Assistive, Never Autonomous

The four hard rules in `CLAUDE.md` bind every feature without exception:

- No automated access to Seek or LinkedIn. No headless browser, no scraping. JD
  text arrives only as something Alan pasted or saved himself.
- No invented experience. Generated content is selected from `profile/`; a
  requirement the profile cannot meet is reported as a gap.
- No auto-submission. The agent produces artefacts; a human sends them.
- Generated prose follows `profile/voice.md`.

A spec whose user story needs any of these to bend is rejected at `/speckit-specify`,
not worked around at `/speckit-plan`.

### II. `core/` Is Callable From Anywhere

`core/` has no `print`, no `typer`, no `sys.exit`, and no I/O beyond the store. The
CLI is a thin shell over it, and the Phase 8 UI must be too. A plan that needs a
change inside `core/` to serve a web handler MUST justify it as a defect in `core/`,
not a UI requirement.

### III. Enforce Mechanically, Don't Ask Nicely

Rules the output must obey are checked in code: hard filters in Python, resume
content copied by reference from `profile/`, numbers traced by `core/validation.py`,
banned phrases parsed from `voice.md`. A plan that relies on a prompt instruction
alone for a hard rule is incomplete. Every validator states its limits honestly —
see the number check in `CLAUDE.md`.

### IV. Tests Never Touch the Network

Every task that changes behaviour ends with the full test suite passing. LLM calls
are mocked in unit tests. `evals/` hits the real API, is never run in CI, and is a
regression detector — no spec or plan may report it as an accuracy figure.

### V. Money Is Stated Before It Is Spent

Every model call goes through `adapters/llm.py`, uses a configured model string and
a prompt file from `prompts/`, and is logged to `runs.jsonl` with its purpose —
failures included. Any feature that adds or changes model calls states the
expected per-run cost in its plan, measured with `jobagent spend` where a
comparable call exists.

### VI. The Repository Is Public

Nothing committed may contain Alan's profile content, salary figures, named
employers from his application history, or anything the profile marks never-publish.
This applies to `specs/` exactly as it applies to code and tests: examples in a
spec, plan, data model or quickstart use invented companies and figures. Before
any commit, check the diff for these, not just the working tree.

`specs/` is committed. The rule above is what makes that safe; gitignoring the
folder instead would trade a checkable rule for a lost history.

## Constraints

- Python 3.12 with `uv`; `typer`, `pydantic` v2, `rich`, `anthropic`,
  `python-docx`, `PyYAML`, `pypdf`, stdlib `sqlite3` with plain SQL, `pytest`.
- A new dependency needs a stated reason in the plan. Readable stdlib beats a
  clever abstraction.
- Document output follows the measured format in `CLAUDE.md`, whose source of
  truth is the master resume. The master wins over any spec.

## Development Workflow

- Spec Kit is for features — Phase 8 and anything of that size. Small fixes and
  profile changes go straight to a commit without a spec.
- Small commits, one task at a time. Do not build ahead of the plan.
- A design decision with a real trade-off is stated and put to Alan, not picked
  silently. `/speckit-clarify` is the place for it.
- Anything that checks "has this been done" looks where the artefacts land, not
  only in SQLite.

## Governance

`CLAUDE.md` takes precedence over this constitution. An invariant added to
`CLAUDE.md` binds immediately; this file is amended only when a principle here
changes. Amendments are committed on their own with the version bumped: MAJOR for
a removed or redefined principle, MINOR for an added one, PATCH for wording.
`/speckit-analyze` checks plans and tasks against this file before
`/speckit-implement`.

**Version**: 1.0.0 | **Ratified**: 2026-09-29 | **Last Amended**: 2026-09-29
