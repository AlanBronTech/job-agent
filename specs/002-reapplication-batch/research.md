# Research: Reapplication Rule and Batch Review

## R1. Requisition extraction

**Decision**: `core/requisition.py`, a regex extractor over the ad's stored text
(the text after platform furniture is removed). Patterns, case-insensitive:

- Workday style: `\bJR[_-]?\d{4,}\b`, and the `R\d{5,}` family when labelled
- Labelled forms: `(requisition|req|job|reference|ref|vacancy|position)\s*(id|no\.?|number|#|code)?\s*[:#]\s*([A-Z0-9][A-Z0-9_\-/]{2,24})`

Rules: the value is stored exactly as written; one distinct match only; more
than one distinct value gives `None`, and the batch row says "several
reference numbers found"; no match gives `None`. Matching for the reapply rule
compares a normalised form (upper case, separators removed), so `JR_000123`
and `JR-000123` match, while the stored text keeps its original form.

**Rationale**: free and deterministic, and it backfills about 70 stored ads in
one pass (FR-017). The ad text already has LinkedIn's furniture (and its
"similar jobs" lists) stripped by `adtext`, so footer numbers are mostly gone,
and the several-values rule covers the rest.

**Alternatives**: a parser prompt field (cannot backfill without paying; a
model may invent a plausible ID); URL parsing (LinkedIn job IDs change on
repost, which is the whole problem).

## R2. Same-job matching

**Decision**: `core/reapply.match(jd, applications, outside, window_days,
today)` returns the strongest match with the date applied:

1. **Same job**: equal normalised requisition ID; or equal `source_url` (an
   existing exact signal); or an earlier application whose ad Alan answered
   "yes, same job" for.
2. **Possibly the same job**: the same company (`history.same_company`), the
   same normalised title (case and punctuation folded, seniority words kept),
   and no requisition ID on **either** side. If both have IDs and they differ,
   it is a different job.

Only applications with an `applied_on` count (tracked or outside). Window:
`today - applied_on < window_days`. Outcome is irrelevant (spec edge case).

**Rationale**: matches clarification Q1 (option B). Different IDs mean
different jobs even with an identical title, which handles a large employer
posting the same title many times.

## R3. Where the rule bites

**Decision**: in `services.scoring.score` and `services.documents.generate`,
after `NoSuchAd` and before every other refusal:

- `SameJobRecently(match)` unless `reapply_overruled` is recorded for the ad;
- `PossiblySameJob(match)` unless an answer is recorded. A "yes" makes it
  `SameJobRecently`; a "no" clears it.

`plan()` (free) reports the state so the UI can show it before confirming.
Parsing is never refused: the parse is what reveals the company and the ID.

**Rationale**: a refusal is raised before spend (Constitution V); the overrule
is recorded like `--force` is today (FR-009).

## R4. The setting

**Decision**: `target_filters.reapply_window_days: 183`, defaulting to 183,
with `null` turning the rule off. Shipped commented in `profile.example`.

## R5. Outside applications and linking

**Decision**: a core table `outside_applications(id, company, title,
requisition_id, applied_on, channel, status, notes, linked_jd_id NULL,
created_at)`. `jobagent apply --outside` records one. `jobagent link <outside>
<jd>` sets `linked_jd_id`, and creates or updates the ad's `applications` row
with the outside record's `applied_on`, status and notes, so there is one
pipeline record (FR-014). History and the reapply rule read both tables.
Linked outside rows are not double-counted.

## R6. Eval leakage (FR-015, and a live defect)

**Decision**: `cases_from_applications` takes the ads' `ingested_at` and leaves
out any application whose `applied_on` is before the ad's capture date. `eval
report` prints how many were left out and why. Outside applications never
enter: they have no ad.

**Rationale**: the CLAUDE.md invariant on observability at decision time. The
case is already in the store today (an application in May, an ad captured in
October).

## R7. Batch "new files"

**Decision**: `job_descriptions.source_file` holds the file name `jd add`
parsed (NULL for paste). A file is new when no ad records it **and** its
modification time is after `meta.batch_baseline`. The baseline is set to now
the first time a batch runs, so the existing folder (~65 files) is never
offered wholesale (spec edge case). `jobagent jd backfill` sets `source_file`
for stored ads where a file's extracted text equals the ad's `raw_text`
exactly (free: PDF and mhtml extraction only), and sets `requisition_id`.

## R8. Batch state and resume

**Decision**: `services/batches.py` owns `batches(id, owner, started_at)` and
`batch_rows(batch_id, file_name, jd_id NULL, refusal NULL, refusal_detail
NULL)`. A row's displayed state is derived: refused, then parsed (jd_id set),
scored (assessment exists), documents (OutputFolders.any), and finally the
application status. Only the refusal is stored. Resume = re-run the batch on
rows with neither a jd_id nor a refusal, so no paid step repeats (FR-007).

## R9. CLI shape

**Decision**: one command group, each step stating its cost and spending only
on an explicit subcommand:

- `jobagent batch` lists the current batch, or the new files with the parse
  cost. Free.
- `jobagent batch parse` parses the new files and prints the table.
- `jobagent score 63 64 65` accepts several ids, prints the combined estimate,
  then scores each, honouring each refusal.
- `jobagent batch skip 64 65` records `not_applied` for each. Free.
- `generate` stays per ad. Each needs its own document choices and clash
  decision, and a batch generate would hide that.
