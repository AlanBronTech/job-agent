# Contract: services and HTTP

## Services (first argument a `Workspace`; refusals raised before any spend)

| Function | Returns / refuses |
|---|---|
| `reapply.check(ws, jd_id, today)` | `Clear` \| `SameJob(match)` \| `PossiblySame(match)`, taking recorded decisions into account. Free. |
| `reapply.decide(ws, jd_id, decision)` | records `same` / `different` / `overrule` |
| `scoring.score(...)`, `documents.generate(...)` | + `SameJobRecently(match)`, `PossiblySameJob(match)` before every other refusal except `NoSuchAd` |
| `documents.plan(...)` | + `reapply` state, for the confirm page |
| `applications.record_outside(ws, *, company, title, requisition_id, applied_on, channel, status, notes)` | `BadDate` |
| `applications.link_outside(ws, outside_id, jd_id)` | `NoSuchAd`; one pipeline record results (research R5) |
| `batches.new_files(ws)` | files with no ad and mtime after the baseline. Free. |
| `batches.start(ws)` → `batch_id`; `batches.rows(ws, batch_id, today)` → rows | free |
| `batches.parse(ws, config, batch_id, *, client_factory=None)` | parses rows with neither a jd_id nor a refusal, via `ads.add`; records refusals |

## HTTP (all POSTs need the token, as in 001)

| Method | Path | |
|---|---|---|
| GET | `/batch` | the current batch table, or the new files with the parse cost |
| POST | `/batch/parse/confirm`, `/batch/parse` | parse new files (confirm, then start one run per file) |
| POST | `/batch/score/confirm`, `/batch/score` | selected ids: combined cost, then one score run each |
| POST | `/batch/skip` | selected ids → `not_applied` |
| POST | `/ads/{id}/reapply` | `decision=same|different|overrule` |

Generate stays per ad (`/ads/{id}/generate/confirm` from 001), linked from
each row; its confirm page shows the reapply state.
