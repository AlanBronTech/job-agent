# Implementation Plan: Master Resumes

**Branch**: `resume-masters` (merged locally, `eccd86b`) | **Date**: 2026-11-16 (as built) | **Spec**: [spec.md](spec.md)

## Summary

Pick, don't compose (D51). A registry of hand-written masters in the
profile; a pure-Python rule that picks one per ad; the choice shown wherever
the assessment is; and the resume that went recorded on the application,
beside what was suggested. Plus `never_in_documents` (D52). No model call is
added and no prompt changes, so the eval set is untouched.

## Technical Context

Python 3.12, pydantic v2, typer, rich, sqlite3, FastAPI + Jinja2 for the UI.
No new dependency. Schema v18 → v19 (two nullable columns, added by the
existing `_ADDED_COLUMNS` mechanism).

## Constitution Check

| Principle | How it is met |
|---|---|
| Hard rules (no scraping, no invented experience, no auto-submit, voice) | Masters are written by the person; JobAgent only picks and records. Nothing is submitted. |
| Core is pure | `core/masters.py` reads files and returns models; no print, no typer. |
| Services shared by CLI and UI | `services/masters.py` (`choose`, `registry`, `resolve_sent`); refusals typed (`UnknownMaster`). |
| Model calls cost money | None added. |
| Tests mock every model | No model in this feature; every test uses invented data. |
| Invented examples | Sam Rivera; Northwind, Acme, Contoso, Fabrikam. |
| **Spec before build** | **Not met**: built from a step list, spec written after (this file). |

## Structure

```
jobagent/core/masters.py        # load_masters, title_shape, select_master, describe_choice
jobagent/core/models.py         # MasterEntry, MastersFile, MasterResume, MasterChoice;
                                # Application.resume_master/_suggested; never_in_documents
jobagent/core/roles.py          # excluded_ids honours never_in_documents
jobagent/core/store.py          # v19 columns
jobagent/services/masters.py    # choose, registry, resolve_sent, SentResume
jobagent/services/{scoring,listing,documents,pipeline,results,refusals}.py
jobagent/cli/{profile,score,apply}.py
jobagent/web/{app,routes}.py, templates/detail.html
profile/resumes/                # gitignored: masters, masters.yaml, old-resumes/
```

## Open work

T017: bring `adapters/docx_writer.py` in line with the masters' layout for a
custom resume. Needs its own design pass: the highlight label is
`**Label:**`, the skills block becomes six paragraphs instead of a table, and
the page-count and number checks must keep passing on the new layout.
