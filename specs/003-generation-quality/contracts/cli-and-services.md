# Contract: CLI and services

## CLI

```text
jobagent generate <id> --resume [--cover] [--answers FILE [--limit N]]
                       [--no-check-claims] [--no-review] [existing flags]
```

Before spending: the estimate now lists each part (writer calls, classify if
not yet done, claim check, review). After: a **Ready** / **Not ready** /
**Not reviewed** line, the coverage table (must-have → highlight/bullet, weak,
or gap), then issues and the unused list as today. `review.md` is written into
the application folder.

`jobagent score <id>` prints the role kind and its reason with the assessment
(classifying first if needed, cost shown).

## Services

| Function | Notes |
|---|---|
| `role_kind.ensure(ws, config, ctx, jd_id) -> RoleKindResult` | classify once, store; free when already stored |
| `checks.check_claims(ws, config, ctx, sentences, evidence) -> list[mismatch] \| NotChecked` | paid; never raises on model failure |
| `checks.review(ws, config, ctx, jd, documents, kind) -> Review \| NotReviewed` | paid; sees ad, policies, documents only |
| `documents.generate(..., check_claims=True, review=True)` | runs role kind → writer → code checks → paid checks; sets `ready` |
| `costs.estimate(ws, config, action)` | + `classify`, `check_claims`, `review` |

## UI

Generate confirm: cover letter unticked by default; two ticked boxes for the
claim check and the review with their costs. Result: Ready / Not ready, the
coverage table, review findings.
