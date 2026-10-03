# Quickstart: validating 002

Invented data only.

## Automated (no network, no cost)

```bash
uv run pytest -q
```

| Proves | Test |
|---|---|
| FR-016/017: extraction exact, none when ambiguous | `tests/test_requisition.py` |
| FR-008/008a/011: same, possibly same, different job | `tests/test_reapply.py` |
| FR-009, SC-001: refused before a client in score and generate; overrule recorded | `tests/test_services_reapply.py` |
| FR-012..014: outside applications and linking | `tests/test_services_applications.py` |
| FR-015 and the live defect: an ad captured after applying is excluded from the eval | `tests/test_evals.py` |
| FR-001..007, SC-003: one row per file, refused rows, resume | `tests/test_services_batches.py`, `tests/test_cli_batch.py`, `tests/test_web_batch.py` |

## Against the real store (free)

1. `jobagent jd backfill`: prints how many requisition ids and source files
   were set. Spot-check three ads.
2. `jobagent apply --outside-list`: empty until you record one.
3. `jobagent eval report`: the count of cases excluded because the ad was
   captured after the application date (at least one is expected).

## The worked example, replayed (≈ $0.04)

Record an outside application for an invented company with an invented
requisition number dated three months ago. Save an invented ad for the same
company and title, without the number, as a `.txt` file. `jobagent batch parse`
shows the row as "possibly the same job". `jobagent score <id>` refuses at no
cost. `jobagent jd same <id> yes`, then score again: refused as the same job.
`jobagent spend` shows only the parse.
