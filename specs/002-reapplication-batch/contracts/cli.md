# Contract: CLI

Every existing command keeps its arguments, messages and exit codes; the new
refusals are added on top.

## Batch

```text
jobagent batch                 # free: the current batch table, or the new files and the parse cost
jobagent batch parse           # parse every new file; prints the table (one row per file)
jobagent batch skip 64 65      # free: record not_applied for each
```

The table columns follow data-model "Batch row". A refused row shows the
reason and the next step (for example: "cut off at '…more': expand the
description, print again, then run `jobagent batch parse`").

## Scoring several

```text
jobagent score 63 64 65
```

Prints the combined estimate, then scores each in turn. A refused ad (thin,
same job, possibly the same job) is reported and skipped; the others go ahead.
Exit code 0 if any were scored, 2 if all were refused.

## The reapplication rule

```text
jobagent score 70
  Same job you applied for on 5 May 2026 (152 days ago, requisition JR_000123).
  The window is 183 days. Nothing was spent. To score it anyway:
    jobagent score 70 --overrule-reapply
  exit 2

jobagent score 71
  Possibly the same job as your application of 5 May 2026 (Fabrikam Medical,
  Engineering Manager, no requisition number on either). Nothing was spent.
    jobagent jd same 71 yes   # same job: the rule applies
    jobagent jd same 71 no    # different job: score normally
  exit 2
```

`generate` gains the same refusals and `--overrule-reapply`. An overrule is
recorded in `reapply_decisions`.

## Outside applications

```text
jobagent outside add --company "Fabrikam Medical" --title "Engineering Manager" \
    --on 2026-05-05 [--req JR_000123] [--channel "careers site"] [--status applied_no_reply] [--note "..."]
jobagent outside list
jobagent outside link <outside_id> <jd_id>
```

Future dates are refused, as `apply` refuses them today. A command group of its
own rather than `apply --outside` (changed during implementation, 2026-10-04):
`apply` keeps its required ad id and its behaviour unchanged.

## Backfill

```text
jobagent jd backfill           # free: requisition_id from stored text; source_file where a saved file's text matches exactly
```
