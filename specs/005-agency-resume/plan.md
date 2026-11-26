# Implementation Plan: Agency Resume

**Branch**: `005-agency-resume` | **Date**: 2026-11-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-agency-resume/spec.md`

## Summary

A resume whose PROFILE is a longer (≤250 words), ad-specific profile, for
recruitment agencies that read a resume instead of a letter. By default a
copy of the chosen master with only its PROFILE paragraphs replaced; also a
custom resume with the longer profile. The master copy's profile is written
by a new cited-sentence prompt on the cover letter's machinery; the custom
kind swaps one rule in the resume prompt, so it costs no extra call. Both go
through the existing checks, claim check and repair, and the 3-page
measurement. What went is recorded (schema v20), and the UI offers the four
resume kinds as one choice. Design choices: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (`uv`)

**Primary Dependencies**: existing only: python-docx, pydantic v2, typer,
rich, FastAPI + Jinja2, pypdf. No new dependency.

**Storage**: SQLite, schema v19 → v20 (one nullable column via
`_ADDED_COLUMNS`); the job folder's JSON resume record gains two keys.

**Testing**: pytest; model calls mocked; fixture master .docx built in the
test; `profile.example/`.

**Target Platform**: macOS, local CLI and local UI.

**Project Type**: CLI + local web UI over a shared service layer.

**Performance Goals**: n/a (one extra model call at most, for the master
kind; the custom kind adds none).

**Constraints**: ≤3 rendered pages; ≤250 profile words; master files never
written; cost shown before spend; masters and profile stay gitignored.

**Scale/Scope**: one person; 3 masters; new code in `core/generate.py`,
`adapters/docx_writer.py`, `services/{documents,masters,costs,revise}.py`,
`core/{models,store}.py`, `cli/{generate,apply}.py`, `web/routes.py`, two
templates, two new prompts, one prompt edited.

## Constitution Check

| Principle | How it is met |
|---|---|
| I. Assistive, never autonomous | Writes files to the job folder; sends nothing. The person reviews and sends. |
| II. `core/` callable from anywhere | `build_profile` and the word cap are pure; the docx edit is in `adapters/`; orchestration in `services/documents.py`. |
| III. Enforce mechanically | 250-word cap, page limit, citations, `never_in_documents`, banned phrases and em-dashes are code checks; the claim check reads every sentence; blockers name the file `_NOT-READY`. |
| IV. Tests never touch the network | All model calls mocked; the suite's key stripping is unchanged. LibreOffice-dependent tests skip without it, as today. |
| V. Money stated before spent | New label `generate_profile` in `services/costs.py`; unmeasured is said, never $0. |
| VI. The repository is public | Specs and tests use Sam Rivera and invented companies; the masters and profile stay gitignored; the diff is checked before each commit. |
| Hard rule 2 (no invented experience) | The longer profile cites profile ids per sentence and is claim-checked; it cannot cite what the profile lacks, and gaps are reported (D37). |
| Hard rule 4 (voice) | `voice.md` banned phrases checked; first person as the masters write. |
| D51 (pick, don't compose) | Bent, deliberately: D53 records why (research R10). The master files are never edited. |
| Development workflow | Spec first (this feature), small commits, tests after each task. |

**Gate**: passes. The one tension (D51) is recorded as a decision, not a
violation.

**Post-design re-check**: unchanged. No new dependency, no new storage
beyond one column and two record keys, no model call that is not priced.

## Project Structure

### Documentation (this feature)

```text
specs/005-agency-resume/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   └── ui.md
├── checklists/requirements.md
└── tasks.md              # /speckit-tasks
```

### Source code (touched)

```text
prompts/
├── generate_profile.md        # new: the master copy's longer profile, cited sentences
├── long_profile_rules.md      # new: what an agency profile does; shared by both prompts
└── generate_resume.md         # rule 7 becomes {profile_rule}
jobagent/core/
├── models.py                  # ResumeKind; Application.resume_long_profile
├── generate.py                # build_profile; LONG_PROFILE_MAX_WORDS; profile_rule in build_resume
└── store.py                   # v20 column; read/write the flag
jobagent/adapters/
└── docx_writer.py             # replace_profile(master, target, paragraphs)
jobagent/services/
├── documents.py               # resume kinds in generate/plan; profile pages loop; record base + flag
├── masters.py                 # SentResume.long_profile; resolve_sent rules (R5)
├── costs.py                   # generate_profile label
├── pipeline.py                # pass the flag through
└── revise.py                  # refuse a master-based resume (R8)
jobagent/cli/
├── generate.py                # --long-profile
└── apply.py                   # --long-profile; status column
jobagent/web/
├── routes.py                  # resume_kind radio; +profile in the Pipeline form
└── templates/{detail,generate_confirm}.html
docs/decisions.md              # D53
README.md, CLAUDE.md           # the option
tests/                         # see quickstart.md
```

**Structure decision**: the existing layout; nothing new at the top level.

## Order of work (for /speckit-tasks)

1. Prompts and `build_profile` (core), with tests on mocked output.
2. `replace_profile` (adapter), with the byte-unchanged test.
3. `services/documents.py`: the `master_profile` path (write, claim check,
   repair, pages, record); then `custom_profile` via `{profile_rule}`.
4. CLI `generate --long-profile` and the cost label.
5. Recording: v20, `resolve_sent`, `apply --long-profile`, `status`.
6. UI: Generate radio, confirmation page, Pipeline form, "Resume sent" line.
7. `revise` refusal; D53; README and CLAUDE.md.
8. By hand, paid, once: quickstart's manual steps; SC-003 page counts into
   the spec.

## Complexity Tracking

None: no constitution violation to justify.
