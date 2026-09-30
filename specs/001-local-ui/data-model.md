# Data Model: Local UI (Phase 8)

Existing entities (`JobDescription`, `FitAssessment`, `Application`,
`ApplicationStatus`, run-log records) are unchanged. This feature adds one table,
one folder-naming rule and two derived views.

## 1. `ui_runs` table (owned by `services/runs.py`; core schema stays v9)

One row per action started from the UI. It records a run, not a model call:
calls stay in `runs.jsonl`, and the two join on `run_id`.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `owner` | TEXT NOT NULL DEFAULT 'local' | the `Workspace.owner` that started it (FR-023) |
| `jd_id` | INTEGER NULL → `job_descriptions(id)` ON DELETE CASCADE | NULL for an `add_ad` until parsing has stored the ad; set on success |
| `kind` | TEXT | `add_ad` \| `score` \| `generate` \| `prep` |
| `status` | TEXT | `running` \| `succeeded` \| `failed` \| `interrupted` |
| `run_id` | TEXT | the `RunContext.run_id` its model calls were logged under |
| `request` | TEXT (JSON) | what was asked: documents selected, overrule given, supersede confirmed, filename |
| `result` | TEXT (JSON) NULL | on success: folder, files written, validation issues, unused entries, superseded folder |
| `error` | TEXT NULL | on failure: the refusal or error message as shown |
| `started_at` / `finished_at` | TEXT ISO-8601 UTC | |
| `seen_at` | TEXT NULL | set when the outcome is viewed; NULL + finished ⇒ announced (FR-016b) |

**Rules**

- At most one `running` row per non-null `jd_id`. Enforced by a check-and-insert
  inside `BEGIN IMMEDIATE`, plus a partial unique index
  `ON ui_runs(jd_id) WHERE status = 'running'` as a backstop.
- `add_ad` rows have no `jd_id` while running, so FR-006 for them is keyed on
  `request["input_key"]`: the file name, or `sha256:<hex>` of pasted text.
  The same input cannot be parsing twice.
- Created by `services/runs.py` with `CREATE TABLE IF NOT EXISTS` on first use.
  `core/store.py` and `SCHEMA_VERSION` are not touched (Constitution II).
- On startup: `UPDATE ui_runs SET status='interrupted', finished_at=now WHERE
  status='running'`.
- `result` holds only what the UI already displayed. It is a copy of service
  output, never a new fact, so it can be lost without losing anything.

**State transitions**

```text
(start) ──► running ──► succeeded
                  ├──► failed
                  └──► interrupted   (server restarted while running)
finished + seen_at NULL ──(viewed or dismissed)──► seen_at set
```

## 2. Superseded folder (filesystem)

```text
OUTPUT_DIR/
  2026-09_AcmeLogistics_EngineeringManager/                          ← current
  2026-09.superseded-20260929T140512_AcmeLogistics_EngineeringManager/  ← superseded
```

- Name: `<YYYY-MM>.superseded-<YYYYMMDDTHHMMSS>_<suffix>`. The part before the
  first `_` contains no underscore, so the existing suffix match finds it.
- Created only by `supersede_folder()` via one `os.rename`. Refused, and nothing
  spent, if the target exists or the rename fails.
- Never deleted or modified by the tool afterwards.
- `is_superseded(folder)`: the prefix contains `.superseded-`.

## 3. Documents on disk (derived)

`services.outputs.documents_for(ws, jd) → OutputFolders`. The `OutputFolders`
type is defined and built in `adapters/document_store.py`:

| Field | Meaning |
|---|---|
| `current` | this month's folder if it exists, with its files and their modification times |
| `superseded` | superseded folders, newest first |
| `earlier` | folders from earlier months (the existing month-scoped behaviour) |
| `any` | True if any of the above holds a `.docx`. This is the "has this been done" answer |

Built from one listing of `OUTPUT_DIR` per page, indexed by suffix. The board's
"documents generated, not recorded" column is: `any` and there is no application
row, or the status is `identified`.

## 4. Cost estimate (derived)

`core.spend.expected_cost(records, labels, model) → CostEstimate`:

| Field | Meaning |
|---|---|
| `per_label` | `{label: (mean_usd, samples) \| "unknown" \| None}` |
| `total_usd` | sum over the selected labels; `None` if any has no measurement; `"unknown"` if any is unknown. Never a partial sum |
| `model` | the model the route resolves to now |
| `budget` | True in budget mode: shown as free tier |

Per label: successful records for that label and model, summed per `run_id`,
averaged across `run_id`s.

## 5. Workspace (not persisted)

| Field | Local value today |
|---|---|
| `owner` | `"local"` |
| `profile_dir`, `db_path`, `runs_log_path`, `jd_dir` | from `.env`, as now |
| `documents` | `LocalFolderStore(OUTPUT_DIR)` |

Built once per CLI command or web request. Services never call `get_config()`.

## 6. Service result and refusal types

Result and refusal types, not persisted. They carry facts, not wording.

| Type | Carries |
|---|---|
| `AddResult` | jd, capture warnings (thin), company history |
| `ScoreResult` | assessment, company history |
| `GenerateResult` | folder, files written, issues, unused entries, superseded folder or None |
| `PrepResult` | prep, issues, file written |
| `NotScored`, `VerdictIsSkip(rationale)`, `ThinAd(chars)`, `CaptureTruncated`, `AlreadyGenerated(folder, files)`, `SupersedeFailed(folder, reason)`, `ProfileMissing`, `ProfileInvalid(detail)`, `NoModel(detail)`, `BadDate(detail)`, `RunInProgress(run)` | refusals, all raised before any model call |
