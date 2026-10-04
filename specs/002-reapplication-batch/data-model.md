# Data Model: Reapplication Rule and Batch Review

Invented examples throughout.

## Core schema v10 (`core/store.py`)

### `job_descriptions` — two added columns

| Column | Type | Notes |
|---|---|---|
| `requisition_id` | TEXT NULL | Exactly as written in the ad (`JR_000123`). NULL when absent or ambiguous. Backfilled from `raw_text`. |
| `source_file` | TEXT NULL | Bare file name `jd add` read from `JD_DIR`. NULL for pasted text and for unmatched older ads. |

### `outside_applications` — new

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `company` | TEXT NOT NULL | Matched with `history.same_company` |
| `title` | TEXT NOT NULL | |
| `requisition_id` | TEXT NULL | |
| `applied_on` | TEXT (date) NOT NULL | Never in the future |
| `channel` | TEXT NULL | |
| `status` | TEXT NOT NULL | `ApplicationStatus` vocabulary |
| `notes` | TEXT NOT NULL DEFAULT '' | |
| `linked_jd_id` | INTEGER NULL → `job_descriptions(id)` ON DELETE SET NULL | Set by `link`; a linked row is not counted twice |
| `created_at` | TEXT | |

### `reapply_decisions` — new

| Column | Type | Notes |
|---|---|---|
| `jd_id` | INTEGER PK → `job_descriptions(id)` ON DELETE CASCADE | One decision per ad |
| `decision` | TEXT | `same` \| `different` \| `overrule` |
| `matched` | TEXT | What it was matched against: `application:<jd_id>`, `outside:<id>` or `ad:<jd_id>` (another stored ad with the same requisition id) |
| `decided_at` | TEXT | |

`same` and `different` answer "possibly the same job". `overrule` waives the
rule for this ad only (spec assumption: one overrule never extends to others).

## Profile (`TargetFilters`)

`reapply_window_days: int | None = 183`. NULL turns the rule off.

## Services-owned (`services/batches.py`)

`batches(id, owner, started_at)`;
`batch_rows(batch_id, file_name, jd_id NULL, refusal NULL, refusal_detail NULL)`.
Row state is derived: `refused` → `parsed` → `scored` → `documents` →
application status. The baseline for "new files" is the `started_at` of the
earliest batch: batch state stays in the service, not in core's `meta`.

## Derived

**Match** (`core/reapply.py`): `kind` (`same` | `possibly_same`), `against`
(application, outside record, or another stored ad with the same requisition id), `applied_on`, `age_days`, `within_window`.

**Batch row** (displayed): file, jd id, company, role, arrangement, salary as
stated, posting metadata, requisition id, hard filters (free), history
summary, reapply flag, verdict and scores if scored, documents, status,
refusal and next step.
