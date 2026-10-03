# Implementation Plan: Reapplication Rule and Batch Review

**Branch**: `002-reapplication-batch` | **Date**: 2026-10-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-reapplication-batch/spec.md`

## Summary

Four pieces, all on the 001 service layer:

1. **Requisition numbers** are pulled out of the ad's stored text by a
   deterministic extractor in `core/`. No prompt change and no model call, so
   existing ads are backfilled for free (FR-016/017).
2. **Outside applications** are a table of their own, not rows in
   `applications` with no ad, so nothing that reads `applications` (the eval
   builder, the board, history) changes meaning by accident (FR-012..015).
3. **The reapplication rule** is a pure match function in `core/reapply.py`,
   called by `services.scoring` and `services.documents` as a refusal before
   any spend, like `ThinAd`. It is not a hard filter in `check_constraints`,
   because those are applied after the model has been paid for (FR-008..011).
4. **Batch review** is `services/batches.py` over a small batch table, shown by
   `jobagent batch` and a `/batch` page. Every action in a batch calls the same
   single-ad service, so it inherits every guard (FR-001..007).

Plus one fix that FR-015 requires but that is already a live defect: the eval
builder grades an application against ad text captured after the decision.
JD-style example: an application in May, ad captured in October.

## Technical Context

**Language/Version**: Python 3.12, `uv`

**Primary Dependencies**: existing only. No new package.

**Storage**: SQLite. `job_descriptions` gains `requisition_id` and
`source_file` (core schema v10). New core table `outside_applications` and
`reapply_decisions`. New services-owned tables `batches` and `batch_rows`.

**Testing**: pytest; model calls mocked; invented ads with invented
requisition numbers.

**Target Platform**: macOS, one user.

**Project Type**: CLI + local web UI over a shared service layer (from 001).

**Performance Goals**: the batch table for 20 rows renders in under 1 s; the
backfill over ~70 stored ads runs in seconds, with no model call.

**Constraints**: no new model calls; no prompt change (the eval set is
unaffected); nothing refused costs anything; no automated access to job
boards.

**Scale/Scope**: about 5–10 ads per batch, about 70 ads stored.

## Constitution Check

| Principle | Status | How |
|---|---|---|
| I. Assistive | Pass | Requisition numbers come only from saved ad text or what Alan types. No fetching. Batch actions still need confirmation and generate nothing unasked. |
| II. `core/` callable from anywhere | Pass, justified | `core/` changes: `requisition_id` and `source_file` columns, `outside_applications`, `reapply_decisions`, `core/reapply.py`, the extractor, and the eval leakage filter. Each serves the CLI and evals as much as the UI, so none is a UI need put into `core/`. Batch state is workflow state and lives in `services/batches.py`, as `ui_runs` does. |
| III. Enforce mechanically | Pass | The rule is a refusal in code before spend, not a prompt instruction. Extraction is a regex with tests, not a model guess. The eval exclusion is computed from dates. |
| IV. No network in tests | Pass | |
| V. Money stated first | Pass | No new model call. A batch shows combined costs from `services.costs` before each paid step. |
| VI. Public repo | Pass | Invented companies and requisition numbers throughout. The real case lives only in the store and in memory. |

## Project Structure

```text
jobagent/
  core/
    requisition.py   # NEW extract_requisition(text) -> str | None, pure
    reapply.py       # NEW match(jd, applications, outside, window_days, today) -> Match | None
    models.py        # JobDescription.requisition_id, .source_file; OutsideApplication;
                     # ReapplyDecision; TargetFilters.reapply_window_days
    store.py         # v10: columns + outside_applications + reapply_decisions
    evals.py         # exclude cases whose ad was captured after applied_on
  services/
    ads.py           # add(): set source_file and requisition_id at parse time
    applications.py  # NEW record_outside, link_outside, list_outside
    reapply.py       # NEW check(ws, jd_id, today) -> Clear | SameJob | PossiblySame;
                     # answer(ws, jd_id, yes|no); overrule(ws, jd_id)
    scoring.py       # + reapply check before spend
    documents.py     # + reapply check before spend
    batches.py       # NEW new_files, start, rows, resume; owns batches/batch_rows
    refusals.py      # + SameJobRecently(match), PossiblySameJob(match)
  cli/
    batch.py         # NEW jobagent batch [parse|score IDS|skip IDS]
    apply.py         # + jobagent apply --outside ...; jobagent link
    jd.py            # + jobagent jd same <id> yes|no ; backfill command
    score.py, generate.py  # map the new refusals; --overrule-reapply
  web/
    routes.py, templates/batch.html, batch_confirm.html  # /batch
    templates/detail.html  # reapply flag, yes/no, overrule
```

## Complexity Tracking

| Choice | Why | Simpler alternative rejected because |
|---|---|---|
| Separate `outside_applications` table | Every reader of `applications` assumes a `jd_id` and an ad. The eval builder, board and history would each need a null check, and the one that missed it would grade a case with no ad text. | **Nullable `applications.jd_id`**: changes the meaning of a table the eval set is built from, which is exactly the kind of change that broke things before (the flattened status enum). |
| A refusal in services, not a hard filter | Hard filters run inside `score_fit`, after the model is paid. The rule's whole point is spending nothing. | **A `ConstraintCheck` breach**: right shape, wrong moment; it would cost $0.11 to be told not to apply. |
| Regex extraction, not the parser prompt | Free, deterministic, testable, backfills old ads, and leaves the prompt and eval set untouched. | **Ask the model**: costs nothing extra at parse time but cannot backfill for free, and a model that does not see a number may supply a plausible one. |
| `batches` tables in services | Resume after interruption needs to remember refusals, which are not otherwise stored. | **Derive everything from the store**: parsed, scored and generated can be derived, but a refused capture leaves no record, which is the bug being fixed. |

## Post-design Constitution Re-check

No change after data-model.md and the contracts. The reapply refusal is raised
before `get_client` in both services, verified by the same booby-trapped
client tests as 001.
