# Contract: HTTP routes (`jobagent/web/`)

Server-rendered HTML. `hx-*` fragments are marked (F). No route takes a URL or a
filesystem path from the client.

**Every request**: `Host` must be `127.0.0.1:<port>` or `localhost:<port>`,
otherwise the response is 403 (R6). **Every POST**: the form field `csrf` must
equal the session cookie, otherwise 403. **Every page** includes the unseen-runs
banner (FR-016b).

## Read — free

| Method | Path | Shows |
|---|---|---|
| GET | `/` | ad list (FR-010); `?sort=date\|score` |
| GET | `/ads/{jd_id}` | detail (FR-011): ad, latest assessment, stale flag, company history, documents on disk (current / superseded / earlier), status, active or last run. Marks that ad's finished runs seen |
| GET | `/board` | pipeline board (FR-014) |
| GET | `/runs/{run_id}` (F) | run status fragment; polled every 2 s while `running`, then stops |

## Confirm — free; renders the cost before anything is spent

| Method | Path | Renders |
|---|---|---|
| POST | `/ads/new/confirm` | file name (drop / newest / paste), parse cost estimate |
| POST | `/ads/{jd_id}/score/confirm` | score cost, thin-ad warning, `force` checkbox if thin |
| POST | `/ads/{jd_id}/generate/confirm` | `documents.plan` result: files, clashes and their times, supersede notice, skip overrule checkbox, cost |
| POST | `/ads/{jd_id}/prep/confirm` | prep cost, interviewers field |

## Spend — start a background run, then 303 to the ad page

| Method | Path | Body | Refusal → |
|---|---|---|---|
| POST | `/ads/new` | `file` (multipart) \| `latest=1` \| `text`; `confirmed=1` | re-render confirm with the reason |
| POST | `/ads/{jd_id}/score` | `force`, `confirmed=1` | 〃 |
| POST | `/ads/{jd_id}/generate` | `resume`, `cover`, `questions`, `overrule`, `supersede`, `confirmed=1` | 〃 |
| POST | `/ads/{jd_id}/prep` | `interviewers`, `confirmed=1` | 〃 |

A spend POST without `confirmed=1`, or with `supersede` missing while a clash
exists, is refused with no run started (FR-004, FR-017). A POST while that ad has
a `running` run returns the existing run (FR-006).

## Record — free

| Method | Path | Body |
|---|---|---|
| POST | `/ads/{jd_id}/status` | `status`, `on`, `channel`, `reposted_on`, `worth`, `why`, `note` |
| POST | `/runs/{run_id}/seen` | — |
| POST | `/ads/{jd_id}/documents/open` | `folder` (name, not path), `name` → `DocumentStore.open`, 204 |
| POST | `/ads/{jd_id}/documents/reveal` | `folder` → `DocumentStore.reveal`, 204 |

`folder` and `name` are checked against `documents_for(jd)`. Anything else is 404.
